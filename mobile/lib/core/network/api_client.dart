import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';
import '../storage/token_storage.dart';
import 'api_exception.dart';

/// HTTP Client abstraction handling headers, authentication, and multipart uploads.
class ApiClient {
  static const Duration defaultTimeout = Duration(seconds: 25);
  final http.Client _client;
  final TokenStorage _tokenStorage;

  ApiClient({
    http.Client? client,
    TokenStorage? tokenStorage,
  })  : _client = client ?? http.Client(),
        _tokenStorage = tokenStorage ?? TokenStorage();

  Future<Map<String, String>> _buildHeaders({
    bool isJson = true,
    bool requiresAuth = false,
    Map<String, String>? extraHeaders,
  }) async {
    final headers = <String, String>{};
    if (isJson) {
      headers['Content-Type'] = 'application/json';
      headers['Accept'] = 'application/json';
    }

    if (requiresAuth) {
      final token = await _tokenStorage.getToken();
      if (token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      } else {
        throw ApiException(
          statusCode: 401,
          message: 'Merchant authentication required. Please sign in.',
        );
      }
    }

    if (extraHeaders != null) {
      headers.addAll(extraHeaders);
    }
    return headers;
  }

  dynamic _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(utf8.decode(response.bodyBytes));
      } catch (_) {
        return response.body;
      }
    }

    String message = 'Request failed with status: ${response.statusCode}';
    dynamic detail;
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic>) {
        if (decoded.containsKey('detail')) {
          final d = decoded['detail'];
          if (d is String) {
            message = d;
          } else {
            message = jsonEncode(d);
            detail = d;
          }
        }
      }
    } catch (_) {
      if (response.body.isNotEmpty) {
        message = response.body;
      }
    }

    throw ApiException(
      statusCode: response.statusCode,
      message: message,
      details: detail,
    );
  }

  Future<dynamic> get(
    String url, {
    Map<String, String>? headers,
    Map<String, dynamic>? queryParams,
    bool requiresAuth = false,
    Duration? timeout,
  }) async {
    Uri uri = Uri.parse(url);
    if (queryParams != null && queryParams.isNotEmpty) {
      final stringParams = queryParams.map(
        (key, value) => MapEntry(key, value?.toString() ?? ''),
      )..removeWhere((key, value) => value.isEmpty);
      uri = uri.replace(queryParameters: stringParams);
    }

    final requestHeaders = await _buildHeaders(
      isJson: true,
      requiresAuth: requiresAuth,
      extraHeaders: headers,
    );

    try {
      final response = await _client
          .get(uri, headers: requestHeaders)
          .timeout(timeout ?? defaultTimeout);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException(statusCode: 408, message: 'Request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(statusCode: 0, message: 'Unable to connect to server. Please check your network connection.');
    }
  }

  Future<Uint8List> getBytes(
    String url, {
    Map<String, String>? headers,
    bool requiresAuth = false,
    Duration? timeout,
  }) async {
    final uri = Uri.parse(url);
    final requestHeaders = await _buildHeaders(
      isJson: false,
      requiresAuth: requiresAuth,
      extraHeaders: headers,
    );

    try {
      final response = await _client
          .get(uri, headers: requestHeaders)
          .timeout(timeout ?? defaultTimeout);
      if (response.statusCode >= 200 && response.statusCode < 300) {
        return response.bodyBytes;
      }
      throw ApiException(
        statusCode: response.statusCode,
        message: 'Failed to load file (status: ${response.statusCode})',
      );
    } on TimeoutException {
      throw ApiException(statusCode: 408, message: 'Request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(statusCode: 0, message: 'Unable to connect to server. Please check your network connection.');
    }
  }

  Future<dynamic> post(
    String url, {
    dynamic body,
    Map<String, String>? headers,
    bool requiresAuth = false,
    Duration? timeout,
  }) async {
    final uri = Uri.parse(url);
    final requestHeaders = await _buildHeaders(
      isJson: true,
      requiresAuth: requiresAuth,
      extraHeaders: headers,
    );

    try {
      final response = await _client
          .post(
            uri,
            headers: requestHeaders,
            body: body != null ? jsonEncode(body) : null,
          )
          .timeout(timeout ?? defaultTimeout);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException(statusCode: 408, message: 'Request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(statusCode: 0, message: 'Unable to connect to server. Please check your network connection.');
    }
  }

  Future<dynamic> delete(
    String url, {
    Map<String, String>? headers,
    bool requiresAuth = false,
  }) async {
    final uri = Uri.parse(url);
    final requestHeaders = await _buildHeaders(
      isJson: true,
      requiresAuth: requiresAuth,
      extraHeaders: headers,
    );

    try {
      final response = await _client.delete(uri, headers: requestHeaders).timeout(defaultTimeout);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException(statusCode: 408, message: 'Request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(statusCode: 0, message: 'Unable to connect to server. Please check your network connection.');
    }
  }

  /// Multipart POST for uploading files (images, videos) and form fields
  Future<dynamic> postMultipart(
    String url, {
    String? fileFieldName,
    String? filename,
    Uint8List? fileBytes,
    String? mimeType,
    Map<String, String>? fields,
    bool requiresAuth = false,
    Duration? timeout,
  }) async {
    final uri = Uri.parse(url);
    final request = http.MultipartRequest('POST', uri);

    final requestHeaders = await _buildHeaders(
      isJson: false,
      requiresAuth: requiresAuth,
    );
    request.headers.addAll(requestHeaders);

    if (fields != null) {
      request.fields.addAll(fields);
    }

    if (fileBytes != null && fileBytes.isNotEmpty) {
      MediaType? parsedMediaType;
      if (mimeType != null && mimeType.contains('/')) {
        final parts = mimeType.split('/');
        parsedMediaType = MediaType(parts[0], parts[1]);
      } else {
        parsedMediaType = MediaType('image', 'jpeg');
      }

      final multipartFile = http.MultipartFile.fromBytes(
        fileFieldName ?? 'file',
        fileBytes,
        filename: filename ?? 'upload.jpg',
        contentType: parsedMediaType,
      );
      request.files.add(multipartFile);
    }

    try {
      final streamedResponse = await _client.send(request).timeout(timeout ?? defaultTimeout);
      final response = await http.Response.fromStream(streamedResponse);
      return _handleResponse(response);
    } on TimeoutException {
      throw ApiException(statusCode: 408, message: 'Request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(statusCode: 0, message: 'Unable to connect to server. Please check your network connection.');
    }
  }
}

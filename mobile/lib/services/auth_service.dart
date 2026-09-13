import '../core/constants/api_endpoints.dart';
import '../core/network/api_client.dart';
import '../core/storage/token_storage.dart';
import '../models/auth_models.dart';

/// Authentication service for merchant login and session management.
class AuthService {
  final ApiClient _apiClient;
  final TokenStorage _tokenStorage;

  AuthService({
    ApiClient? apiClient,
    TokenStorage? tokenStorage,
  })  : _apiClient = apiClient ?? ApiClient(),
        _tokenStorage = tokenStorage ?? TokenStorage();

  Future<AuthTokens> login({
    required String email,
    required String password,
  }) async {
    final response = await _apiClient.post(
      ApiEndpoints.login,
      body: LoginRequest(email: email, password: password).toJson(),
    );

    final tokens = AuthTokens.fromJson(response as Map<String, dynamic>);
    await _tokenStorage.saveToken(tokens.accessToken);
    await _tokenStorage.setCustomerMode(false);
    return tokens;
  }

  Future<void> logout() async {
    await _tokenStorage.clearToken();
  }

  Future<bool> isLoggedIn() async {
    final token = await _tokenStorage.getToken();
    return token != null && token.isNotEmpty;
  }

  Future<String?> getToken() => _tokenStorage.getToken();
}

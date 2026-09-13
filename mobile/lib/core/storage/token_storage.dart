import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Secure token storage for merchant authentication and user preferences.
/// Uses a singleton pattern with synchronous static in-memory caching
/// and encrypted persistent storage.
class TokenStorage {
  static const String _keyToken = 'merchant_auth_token';
  static const String _keyCustomerMode = 'customer_mode_active';
  static const String _keyBaseUrl = 'saved_base_url';

  static final TokenStorage _instance = TokenStorage._internal();

  factory TokenStorage({FlutterSecureStorage? secureStorage}) {
    if (secureStorage != null) {
      _instance._customSecureStorage = secureStorage;
    }
    return _instance;
  }

  TokenStorage._internal();

  static const AndroidOptions _androidOptions = AndroidOptions(
    encryptedSharedPreferences: true,
    resetOnError: true,
  );
  static const IOSOptions _iosOptions = IOSOptions(
    accessibility: KeychainAccessibility.first_unlock,
  );

  FlutterSecureStorage? _customSecureStorage;
  FlutterSecureStorage get _secureStorage =>
      _customSecureStorage ??
      const FlutterSecureStorage(
        aOptions: _androidOptions,
        iOptions: _iosOptions,
      );

  SharedPreferences? _prefs;

  // Static shared in-memory caches accessible across all instances synchronously
  static String? _cachedToken;
  static bool? _cachedCustomerMode;
  static String? _cachedBaseUrl;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  // Token Management
  Future<void> saveToken(String token) async {
    _cachedToken = token;
    _prefs ??= await SharedPreferences.getInstance();
    await _prefs?.setString(_keyToken, token);
    try {
      await _secureStorage.write(key: _keyToken, value: token);
    } catch (_) {
      // Fallback in memory and SharedPreferences
    }
  }

  Future<String?> getToken() async {
    if (_cachedToken != null && _cachedToken!.isNotEmpty) {
      return _cachedToken;
    }
    try {
      final token = await _secureStorage.read(key: _keyToken);
      if (token != null && token.isNotEmpty) {
        _cachedToken = token;
        return token;
      }
    } catch (_) {
      // Fallback
    }
    _prefs ??= await SharedPreferences.getInstance();
    try {
      await _prefs?.reload();
    } catch (_) {}
    final prefToken = _prefs?.getString(_keyToken);
    if (prefToken != null && prefToken.isNotEmpty) {
      _cachedToken = prefToken;
      return prefToken;
    }
    return _cachedToken;
  }

  Future<void> clearToken() async {
    _cachedToken = null;
    _prefs ??= await SharedPreferences.getInstance();
    await _prefs?.remove(_keyToken);
    try {
      await _secureStorage.delete(key: _keyToken);
    } catch (_) {
      // Fallback
    }
  }

  // Customer Mode Preference
  Future<void> setCustomerMode(bool active) async {
    _cachedCustomerMode = active;
    _prefs ??= await SharedPreferences.getInstance();
    await _prefs?.setBool(_keyCustomerMode, active);
  }

  Future<bool> isCustomerMode() async {
    if (_cachedCustomerMode != null) return _cachedCustomerMode!;
    _prefs ??= await SharedPreferences.getInstance();
    final mode = _prefs?.getBool(_keyCustomerMode) ?? false;
    _cachedCustomerMode = mode;
    return mode;
  }

  // Saved Base URL
  Future<void> saveBaseUrl(String url) async {
    _cachedBaseUrl = url;
    _prefs ??= await SharedPreferences.getInstance();
    await _prefs?.setString(_keyBaseUrl, url);
  }

  Future<String?> getSavedBaseUrl() async {
    if (_cachedBaseUrl != null && _cachedBaseUrl!.isNotEmpty) {
      return _cachedBaseUrl;
    }
    _prefs ??= await SharedPreferences.getInstance();
    final url = _prefs?.getString(_keyBaseUrl);
    _cachedBaseUrl = url;
    return url;
  }

  /// Visible for testing to reset cache
  static void resetCacheForTesting() {
    _cachedToken = null;
    _cachedCustomerMode = null;
    _cachedBaseUrl = null;
  }
}

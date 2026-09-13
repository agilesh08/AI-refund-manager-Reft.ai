/// Authentication data models for Merchant Auth.
class LoginRequest {
  final String email;
  final String password;

  LoginRequest({required this.email, required this.password});

  Map<String, dynamic> toJson() => {
        'email': email,
        'password': password,
      };
}

class AuthTokens {
  final String accessToken;
  final String tokenType;

  AuthTokens({required this.accessToken, required this.tokenType});

  factory AuthTokens.fromJson(Map<String, dynamic> json) {
    return AuthTokens(
      accessToken: json['access_token'] as String? ?? '',
      tokenType: json['token_type'] as String? ?? 'bearer',
    );
  }
}

class MerchantProfile {
  final String id;
  final String email;
  final String businessName;
  final bool isActive;

  MerchantProfile({
    required this.id,
    required this.email,
    required this.businessName,
    required this.isActive,
  });

  factory MerchantProfile.fromJson(Map<String, dynamic> json) {
    return MerchantProfile(
      id: json['id'] as String? ?? '',
      email: json['email'] as String? ?? '',
      businessName: json['business_name'] as String? ?? '',
      isActive: json['is_active'] as bool? ?? true,
    );
  }
}

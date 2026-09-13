/// Custom exception for API errors.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final dynamic details;

  ApiException({
    required this.statusCode,
    required this.message,
    this.details,
  });

  bool get isUnauthorized => statusCode == 401;
  bool get isForbidden => statusCode == 403;
  bool get isNotFound => statusCode == 404;
  bool get isGone => statusCode == 410; // Token expired / cancelled
  bool get isLocked => statusCode == 423; // Verification paused / held
  bool get isTimeout => statusCode == 408;
  bool get isValidationError => statusCode == 422;
  bool get isServerError => statusCode >= 500;
  bool get isNetworkError => statusCode == 0;

  String get userTitle {
    final lower = message.toLowerCase();
    if (isLocked || lower.contains('paused') || lower.contains('held')) {
      return 'Verification Temporarily Paused';
    }
    if (lower.contains('already completed') || lower.contains('attempts exceeded')) {
      return 'Verification Already Completed';
    }
    if (isGone || lower.contains('expired')) {
      return 'Session Expired';
    }
    if (isNotFound || lower.contains('invalid verification token') || lower.contains('not found')) {
      return 'Verification Not Found';
    }
    if (isUnauthorized) {
      return 'Invalid Credentials';
    }
    if (isForbidden) {
      return 'Access Denied';
    }
    if (isTimeout) {
      return 'Request Timed Out';
    }
    if (isNetworkError) {
      return 'Connection Error';
    }
    if (isServerError) {
      return 'Something Went Wrong';
    }
    if (isValidationError) {
      return 'Validation Error';
    }
    return 'Action Failed';
  }

  String get userMessage {
    final lower = message.toLowerCase();
    if (isLocked || lower.contains('paused') || lower.contains('held')) {
      return 'Verification temporarily paused. Your merchant has paused this verification session. Please check back later or contact the store.';
    }
    if (lower.contains('already completed') || lower.contains('attempts exceeded')) {
      return 'This verification session has already been completed and cannot be reopened.';
    }
    if (isGone || lower.contains('expired')) {
      return 'This verification link has expired. Please request a new link from the merchant.';
    }
    if (isNotFound || lower.contains('not found') || lower.contains('invalid verification token')) {
      return 'Verification not found. The verification code may be invalid or expired.';
    }
    if (isUnauthorized) {
      if (lower.contains('invalid email') || lower.contains('password') || lower.contains('credential')) {
        return 'Invalid email or password. Please check your credentials and try again.';
      }
      return 'Your session has expired. Please log in again to continue.';
    }
    if (isForbidden) {
      return 'You do not have permission to perform this action.';
    }
    if (isTimeout) {
      return 'The request took too long to complete. Please check your connection and try again.';
    }
    if (isNetworkError) {
      return 'Unable to reach the server. Please check your connection or server configuration.';
    }
    if (isServerError) {
      return 'Something went wrong on our end. Please try again in a few moments.';
    }
    if (isValidationError && details is List) {
      final messages = (details as List)
          .map((e) => e is Map ? (e['msg'] ?? e.toString()) : e.toString())
          .where((s) => s.isNotEmpty)
          .join('\n');
      if (messages.isNotEmpty) return messages;
    }
    return message.isNotEmpty ? message : 'An unexpected error occurred. Please try again.';
  }

  @override
  String toString() => userMessage;
}

import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/core/constants/api_endpoints.dart';
import 'package:refund_verification_app/core/constants/app_colors.dart';
import 'package:refund_verification_app/core/network/api_exception.dart';

void main() {
  group('API and Core Utilities Tests', () {
    test('ApiException status helpers', () {
      final authErr = ApiException(statusCode: 401, message: 'Unauthorized');
      expect(authErr.isUnauthorized, true);
      expect(authErr.isForbidden, false);

      final goneErr = ApiException(statusCode: 410, message: 'Session expired');
      expect(goneErr.isGone, true);
      expect(goneErr.isNotFound, false);

      final notFoundErr = ApiException(statusCode: 404, message: 'Not found');
      expect(notFoundErr.isNotFound, true);

      final valErr = ApiException(statusCode: 422, message: 'Validation error');
      expect(valErr.isValidationError, true);
    });

    test('ApiEndpoints base URL customization', () {
      ApiEndpoints.setBaseUrl('https://api.example.com/');
      expect(ApiEndpoints.baseUrl, 'https://api.example.com');
      expect(ApiEndpoints.login, 'https://api.example.com/api/v1/auth/login');
      expect(ApiEndpoints.customerOverview('tok_123'),
          'https://api.example.com/api/v1/public/verifications/tok_123');
      expect(ApiEndpoints.verificationDashboard('sess_456'),
          'https://api.example.com/api/v1/verifications/sess_456/dashboard');

      // Reset
      ApiEndpoints.setBaseUrl('http://10.0.2.2:8000');
    });

    test('AppColors assessment and decision status mappings', () {
      // Assessment colors
      expect(AppColors.forAssessment('EVIDENCE_CONSISTENT'),
          AppColors.assessmentConsistent);
      expect(AppColors.forAssessment('REVIEW_REQUIRED'),
          AppColors.assessmentReviewRequired);
      expect(AppColors.forAssessment('INCONSISTENCY_DETECTED'),
          AppColors.assessmentInconsistent);

      // Decision colors
      expect(AppColors.forDecision('REFUND_APPROVED'),
          AppColors.decisionApproved);
      expect(AppColors.forDecision('REFUND_REJECTED'),
          AppColors.decisionRejected);
      expect(AppColors.forDecision('MANUAL_REVIEW'),
          AppColors.decisionManualReview);

      // Status colors
      expect(AppColors.forStatus('CREATED'), AppColors.statusCreated);
      expect(AppColors.forStatus('IN_PROGRESS'), AppColors.statusInProgress);
      expect(AppColors.forStatus('COMPLETED'), AppColors.statusCompleted);
    });
  });
}

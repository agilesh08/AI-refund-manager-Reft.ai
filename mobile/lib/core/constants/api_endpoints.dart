/// API Endpoints for Refund Evidence Verification System.
class ApiEndpoints {
  // Default base URL points to 10.0.2.2 for Android Emulator, or localhost for web/desktop.
  // Overridable at runtime or compile-time via --dart-define=API_BASE_URL=...
  static String defaultBaseUrl = const String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  // Dynamic base URL that can be altered by user in Gateway Settings
  static String baseUrl = defaultBaseUrl;

  static void setBaseUrl(String url) {
    String cleaned = url.trim();
    if (cleaned.isEmpty) return;
    if (!cleaned.startsWith('http://') && !cleaned.startsWith('https://')) {
      cleaned = 'http://$cleaned';
    }
    while (cleaned.endsWith('/')) {
      cleaned = cleaned.substring(0, cleaned.length - 1);
    }
    if (cleaned.endsWith('/api/v1')) {
      cleaned = cleaned.substring(0, cleaned.length - 7);
    } else if (cleaned.endsWith('/api')) {
      cleaned = cleaned.substring(0, cleaned.length - 4);
    }
    while (cleaned.endsWith('/')) {
      cleaned = cleaned.substring(0, cleaned.length - 1);
    }
    baseUrl = cleaned;
  }

  // Auth
  static String get login => '$baseUrl/api/v1/auth/login';

  // Products
  static String get products => '$baseUrl/api/v1/products';
  static String productDetail(String id) => '$baseUrl/api/v1/products/$id';
  static String productCompleteness(String id) => '$baseUrl/api/v1/products/$id/completeness';
  static String productReferences(String id) => '$baseUrl/api/v1/products/$id/references';
  static String productReferenceAngle(String id, String angle) => '$baseUrl/api/v1/products/$id/references/$angle';
  static String productReferenceFile(String id, String angle) => '$baseUrl/api/v1/products/$id/references/$angle/file';

  // Merchant Endpoints
  static String get verifications => '$baseUrl/api/v1/verifications';
  static String verificationDetail(String id) => '$baseUrl/api/v1/verifications/$id';
  static String verificationDashboard(String id) => '$baseUrl/api/v1/verifications/$id/dashboard';
  static String verificationReport(String id) => '$baseUrl/api/v1/verifications/$id/report';
  static String verificationTimeline(String id) => '$baseUrl/api/v1/verifications/$id/timeline';
  static String verificationDecision(String id) => '$baseUrl/api/v1/verifications/$id/decision';
  static String verificationDecisions(String id) => '$baseUrl/api/v1/verifications/$id/decisions';
  static String verificationHold(String id) => '$baseUrl/api/v1/verifications/$id/hold';
  static String verificationResume(String id) => '$baseUrl/api/v1/verifications/$id/resume';
  static String verificationDelete(String id) => '$baseUrl/api/v1/verifications/$id';

  // Public Customer Endpoints
  static String customerOverview(String token) => '$baseUrl/api/v1/public/verifications/$token';
  static String customerStart(String token) => '$baseUrl/api/v1/public/verifications/$token/start';
  static String customerWorkflow(String token) => '$baseUrl/api/v1/public/verifications/$token/workflow';
  static String customerEvidenceImage(String token) => '$baseUrl/api/v1/public/verifications/$token/evidence/image';
  static String customerEvidenceText(String token) => '$baseUrl/api/v1/public/verifications/$token/evidence/text';
  static String customerEvidenceList(String token) => '$baseUrl/api/v1/public/verifications/$token/evidence';
  static String customerEvidenceFile(String token, String evidenceId) =>
      '$baseUrl/api/v1/public/verifications/$token/evidence/$evidenceId';
  static String customerEvidenceRequests(String token) => '$baseUrl/api/v1/public/verifications/$token/evidence-requests';
  static String customerFulfillRequest(String token, String requestId) =>
      '$baseUrl/api/v1/public/verifications/$token/evidence-requests/$requestId/fulfill';
  static String customerSignals(String token) => '$baseUrl/api/v1/public/verifications/$token/signals';
  static String customerFusion(String token) => '$baseUrl/api/v1/public/verifications/$token/fusion';
  static String customerAnalyze(String token) => '$baseUrl/api/v1/public/verifications/$token/analyze';
  static String customerComplete(String token) => '$baseUrl/api/v1/public/verifications/$token/complete';
  static String customerExtractPaymentProof(String token) =>
      '$baseUrl/api/v1/public/verifications/$token/extract-payment-proof';
  static String customerSubmitPaymentProof(String token) =>
      '$baseUrl/api/v1/public/verifications/$token/payment-proof';

  // Workflow Builder Endpoints
  static String get workflows => '$baseUrl/api/v1/workflows';
  static String workflowDetail(String id) => '$baseUrl/api/v1/workflows/$id';
  static String workflowSteps(String id) => '$baseUrl/api/v1/workflows/$id/steps';
  static String workflowStepDetail(String id, String stepId) => '$baseUrl/api/v1/workflows/$id/steps/$stepId';
  static String workflowPublish(String id) => '$baseUrl/api/v1/workflows/$id/publish';
}

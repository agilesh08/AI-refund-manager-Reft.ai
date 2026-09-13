import 'dart:typed_data';
import '../core/constants/api_endpoints.dart';
import '../core/network/api_client.dart';
import '../models/merchant_decision_models.dart';
import '../models/report_models.dart';

/// Merchant operations service consuming authenticated endpoints.
class MerchantService {
  final ApiClient _apiClient;

  MerchantService({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient();

  Future<DashboardVerificationListModel> listVerifications({
    String? status,
    String? assessmentState,
    String? search,
    String? orderId,
    String? productId,
    int page = 1,
    int pageSize = 20,
  }) async {
    final queryParams = <String, dynamic>{
      'page': page,
      'page_size': pageSize,
    };
    if (status != null && status.isNotEmpty && status != 'ALL') {
      queryParams['status'] = status;
    }
    if (assessmentState != null &&
        assessmentState.isNotEmpty &&
        assessmentState != 'ALL') {
      queryParams['assessment_state'] = assessmentState;
    }
    if (search != null && search.isNotEmpty) {
      queryParams['search'] = search;
    }
    if (orderId != null && orderId.isNotEmpty) {
      queryParams['order_id'] = orderId;
    }
    if (productId != null && productId.isNotEmpty) {
      queryParams['product_id'] = productId;
    }

    final response = await _apiClient.get(
      ApiEndpoints.verifications,
      queryParams: queryParams,
      requiresAuth: true,
    );

    if (response is Map<String, dynamic>) {
      return DashboardVerificationListModel.fromJson(response);
    } else if (response is List) {
      // Backward compatibility fallback
      final items = response
          .map((item) => DashboardVerificationItemModel.fromJson(
              item as Map<String, dynamic>))
          .toList();
      return DashboardVerificationListModel(
        items: items,
        total: items.length,
        page: page,
        pageSize: pageSize,
      );
    }
    return DashboardVerificationListModel(items: []);
  }

  Future<VerificationDetailDashboardModel> getInvestigationDetail(
      String verificationId) async {
    final response = await _apiClient.get(
      ApiEndpoints.verificationDashboard(verificationId),
      requiresAuth: true,
    );
    return VerificationDetailDashboardModel.fromJson(
        response as Map<String, dynamic>);
  }

  Future<ExplainableVerificationReportModel> getReport(
      String verificationId) async {
    final response = await _apiClient.get(
      ApiEndpoints.verificationReport(verificationId),
      requiresAuth: true,
    );
    return ExplainableVerificationReportModel.fromJson(
        response as Map<String, dynamic>);
  }

  Future<List<TimelineItemModel>> getTimeline(String verificationId) async {
    final response = await _apiClient.get(
      ApiEndpoints.verificationTimeline(verificationId),
      requiresAuth: true,
    );
    final list = response as List<dynamic>? ?? [];
    return list
        .map((t) => TimelineItemModel.fromJson(t as Map<String, dynamic>))
        .toList();
  }

  Future<MerchantDecisionModel> recordDecision({
    required String verificationId,
    required MerchantDecisionCreate decision,
  }) async {
    final response = await _apiClient.post(
      ApiEndpoints.verificationDecision(verificationId),
      body: decision.toJson(),
      requiresAuth: true,
    );
    return MerchantDecisionModel.fromJson(response as Map<String, dynamic>);
  }

  Future<List<MerchantDecisionModel>> listDecisions(
      String verificationId) async {
    final response = await _apiClient.get(
      ApiEndpoints.verificationDecisions(verificationId),
      requiresAuth: true,
    );
    final list = response as List<dynamic>? ?? [];
    return list
        .map((d) => MerchantDecisionModel.fromJson(d as Map<String, dynamic>))
        .toList();
  }

  Future<Map<String, dynamic>> holdVerification({
    required String verificationId,
    int? durationSeconds,
    String? reason,
  }) async {
    final response = await _apiClient.post(
      ApiEndpoints.verificationHold(verificationId),
      body: {
        'duration_seconds': ?durationSeconds,
        'reason': ?reason,
      },
      requiresAuth: true,
    );
    return response as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> resumeVerification(String verificationId) async {
    final response = await _apiClient.post(
      ApiEndpoints.verificationResume(verificationId),
      body: {},
      requiresAuth: true,
    );
    return response as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> deleteVerification(String verificationId) async {
    final response = await _apiClient.delete(
      ApiEndpoints.verificationDelete(verificationId),
      requiresAuth: true,
    );
    return (response is Map<String, dynamic>) ? response : {'success': true};
  }

  // -------------------------------------------------------------------------
  // Workflow Builder Endpoints
  // -------------------------------------------------------------------------

  Future<List<Map<String, dynamic>>> listWorkflows() async {
    final response = await _apiClient.get(
      ApiEndpoints.workflows,
      requiresAuth: true,
    );
    final list = response as List<dynamic>? ?? [];
    return list.map((w) => Map<String, dynamic>.from(w as Map)).toList();
  }

  Future<Map<String, dynamic>> getWorkflow(String workflowId) async {
    final response = await _apiClient.get(
      ApiEndpoints.workflowDetail(workflowId),
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<Map<String, dynamic>> createWorkflow(String name,
      {String? description}) async {
    final response = await _apiClient.post(
      ApiEndpoints.workflows,
      body: {
        'name': name,
        'description': description ?? 'Custom refund verification workflow',
      },
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<Map<String, dynamic>> addWorkflowStep({
    required String workflowId,
    required String stepKey,
    required String stepType,
    required String title,
    String? description,
    required int stepOrder,
    bool required = true,
    Map<String, dynamic>? config,
  }) async {
    final response = await _apiClient.post(
      ApiEndpoints.workflowSteps(workflowId),
      body: {
        'step_key': stepKey,
        'step_type': stepType,
        'title': title,
        'description': description,
        'step_order': stepOrder,
        'required': required,
        'config': config ?? {},
      },
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<void> deleteWorkflowStep(String workflowId, String stepId) async {
    await _apiClient.delete(
      ApiEndpoints.workflowStepDetail(workflowId, stepId),
      requiresAuth: true,
    );
  }

  Future<Map<String, dynamic>> publishWorkflow(String workflowId) async {
    final response = await _apiClient.post(
      ApiEndpoints.workflowPublish(workflowId),
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  // -------------------------------------------------------------------------
  // Products & Verification Creation
  // -------------------------------------------------------------------------

  Future<List<Map<String, dynamic>>> listProducts() async {
    final response = await _apiClient.get(
      ApiEndpoints.products,
      requiresAuth: true,
    );
    final list = response as List<dynamic>? ?? [];
    return list.map((p) => Map<String, dynamic>.from(p as Map)).toList();
  }

  Future<Map<String, dynamic>> createVerificationSession({
    required String productId,
    required String workflowId,
    required String orderId,
    String? customerName,
    String? customerContact,
    String? refundReason,
    double? refundAmount,
    int maxAttempts = 1,
  }) async {
    final body = <String, dynamic>{
      'product_id': productId,
      'workflow_id': workflowId,
      'order_id': orderId,
      if (customerName != null && customerName.trim().isNotEmpty)
        'customer_name': customerName.trim(),
      if (customerContact != null && customerContact.trim().isNotEmpty)
        'customer_contact': customerContact.trim(),
      if (refundReason != null && refundReason.trim().isNotEmpty)
        'refund_reason': refundReason.trim(),
      if (refundAmount != null && refundAmount > 0)
        'refund_amount': refundAmount,
      'max_attempts': maxAttempts,
    };

    final response = await _apiClient.post(
      ApiEndpoints.verifications,
      body: body,
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  // -------------------------------------------------------------------------
  // Product & Reference Evidence Management
  // -------------------------------------------------------------------------

  Future<Map<String, dynamic>> createProduct({
    required String name,
    required String sku,
    String? description,
    double? price,
  }) async {
    final body = <String, dynamic>{
      'name': name.trim(),
      'sku': sku.trim(),
      if (description != null && description.trim().isNotEmpty)
        'description': description.trim(),
      if (price != null && price >= 0) 'price': price,
    };

    final response = await _apiClient.post(
      ApiEndpoints.products,
      body: body,
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<void> deleteProduct(String productId) async {
    await _apiClient.delete(
      ApiEndpoints.productDetail(productId),
      requiresAuth: true,
    );
  }

  Future<Map<String, dynamic>> getProductCompleteness(String productId) async {
    final response = await _apiClient.get(
      ApiEndpoints.productCompleteness(productId),
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<List<Map<String, dynamic>>> listProductReferences(
      String productId) async {
    final response = await _apiClient.get(
      ApiEndpoints.productReferences(productId),
      requiresAuth: true,
    );
    final list = response as List<dynamic>? ?? [];
    return list.map((r) => Map<String, dynamic>.from(r as Map)).toList();
  }

  Future<Map<String, dynamic>> uploadProductReference({
    required String productId,
    required String angle,
    required Uint8List fileBytes,
    required String filename,
    String? mimeType,
  }) async {
    final response = await _apiClient.postMultipart(
      ApiEndpoints.productReferences(productId),
      fileFieldName: 'image',
      filename: filename,
      fileBytes: fileBytes,
      mimeType: mimeType ?? 'image/jpeg',
      fields: {'angle': angle.toUpperCase()},
      requiresAuth: true,
    );
    return Map<String, dynamic>.from(response as Map);
  }

  Future<void> deleteProductReference(String productId, String angle) async {
    await _apiClient.delete(
      ApiEndpoints.productReferenceAngle(productId, angle.toUpperCase()),
      requiresAuth: true,
    );
  }

  Future<Uint8List> getReferenceImageBytes(
      String productId, String angle) async {
    return await _apiClient.getBytes(
      ApiEndpoints.productReferenceFile(productId, angle.toUpperCase()),
      requiresAuth: true,
    );
  }

  Future<Map<String, dynamic>> extractOrder({
    Uint8List? imageBytes,
    String? filename,
    String? text,
  }) async {
    final response = await _apiClient.postMultipart(
      '${ApiEndpoints.verifications}/extract-order',
      fileFieldName: 'file',
      filename: filename ?? 'order_screenshot.jpg',
      fileBytes: imageBytes,
      fields: text != null && text.isNotEmpty ? {'text': text} : null,
      requiresAuth: true,
    );
    if (response is Map<String, dynamic> &&
        response['extracted'] is Map<String, dynamic>) {
      return Map<String, dynamic>.from(response['extracted'] as Map);
    }
    return {};
  }
}

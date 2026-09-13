import 'dart:typed_data';
import '../core/constants/api_endpoints.dart';
import '../core/network/api_client.dart';
import '../models/customer_verification.dart';
import '../models/evidence_models.dart';
import '../models/fusion_models.dart';
import '../models/signal_models.dart';
import '../models/workflow_step.dart';

/// Public customer verification API service.
class CustomerVerificationService {
  final ApiClient _apiClient;

  CustomerVerificationService({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient();

  Future<CustomerVerificationResponse> getOverview(String token) async {
    final response = await _apiClient.get(ApiEndpoints.customerOverview(token));
    return CustomerVerificationResponse.fromJson(
        response as Map<String, dynamic>);
  }

  Future<VerificationStartResponse> startVerification(String token) async {
    final response = await _apiClient.post(ApiEndpoints.customerStart(token));
    return VerificationStartResponse.fromJson(
        response as Map<String, dynamic>);
  }

  Future<CustomerWorkflowResponse> getWorkflow(String token) async {
    final response = await _apiClient.get(ApiEndpoints.customerWorkflow(token));
    return CustomerWorkflowResponse.fromJson(
        response as Map<String, dynamic>);
  }

  Future<EvidenceResponseModel> uploadImageEvidence({
    required String token,
    required Uint8List fileBytes,
    required String filename,
    String? workflowStepKey,
  }) async {
    final fields = <String, String>{};
    if (workflowStepKey != null) {
      fields['workflow_step_key'] = workflowStepKey;
    }

    final response = await _apiClient.postMultipart(
      ApiEndpoints.customerEvidenceImage(token),
      fileFieldName: 'file',
      filename: filename,
      fileBytes: fileBytes,
      fields: fields,
    );
    return EvidenceResponseModel.fromJson(response as Map<String, dynamic>);
  }

  Future<EvidenceResponseModel> submitTextEvidence({
    required String token,
    required String textContent,
    String? workflowStepKey,
  }) async {
    final body = <String, dynamic>{
      'text': textContent,
      'text_content': textContent,
    };
    if (workflowStepKey != null) {
      body['workflow_step_key'] = workflowStepKey;
    }

    final response = await _apiClient.post(
      ApiEndpoints.customerEvidenceText(token),
      body: body,
    );
    return EvidenceResponseModel.fromJson(response as Map<String, dynamic>);
  }

  Future<List<EvidenceResponseModel>> listEvidence(
    String token, {
    String? workflowStepKey,
  }) async {
    final query = <String, dynamic>{};
    if (workflowStepKey != null) {
      query['workflow_step_key'] = workflowStepKey;
    }
    final response = await _apiClient.get(
      ApiEndpoints.customerEvidenceList(token),
      queryParams: query,
    );
    final list = response as List<dynamic>? ?? [];
    return list
        .map((e) => EvidenceResponseModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<CustomerEvidenceRequestModel>> listEvidenceRequests(
      String token) async {
    final response =
        await _apiClient.get(ApiEndpoints.customerEvidenceRequests(token));
    final list = response as List<dynamic>? ?? [];
    return list
        .map((e) =>
            CustomerEvidenceRequestModel.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<EvidenceFulfillResult> fulfillEvidenceRequest({
    required String token,
    required String requestId,
    Uint8List? fileBytes,
    String? filename,
    String? textContent,
    String? selectedOption,
  }) async {
    final fields = <String, String>{
      if (textContent != null && textContent.isNotEmpty)
        'text_content': textContent,
      if (selectedOption != null && selectedOption.isNotEmpty)
        'selected_option': selectedOption,
    };

    final response = await _apiClient.postMultipart(
      ApiEndpoints.customerFulfillRequest(token, requestId),
      fileFieldName: 'file',
      filename: filename,
      fileBytes: fileBytes,
      fields: fields.isNotEmpty ? fields : null,
    );
    return EvidenceFulfillResult.fromJson(response as Map<String, dynamic>);
  }

  Future<List<CustomerSignalModel>> getSignals(String token) async {
    final response = await _apiClient.get(ApiEndpoints.customerSignals(token));
    final list = response as List<dynamic>? ?? [];
    return list
        .map((s) => CustomerSignalModel.fromJson(s as Map<String, dynamic>))
        .toList();
  }

  Future<CustomerFusionModel> getFusion(String token) async {
    final response = await _apiClient.get(ApiEndpoints.customerFusion(token));
    return CustomerFusionModel.fromJson(response as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> triggerAnalysis(String token) async {
    final response = await _apiClient.post(
      ApiEndpoints.customerAnalyze(token),
      timeout: const Duration(seconds: 60),
    );
    return (response is Map<String, dynamic>)
        ? response
        : <String, dynamic>{'status': 'READY_FOR_REVIEW'};
  }

  Future<VerificationStartResponse> completeSession(String token) async {
    final response = await _apiClient.post(ApiEndpoints.customerComplete(token));
    return VerificationStartResponse.fromJson(response as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> extractPaymentProof({
    required String token,
    required Uint8List fileBytes,
    required String filename,
  }) async {
    final response = await _apiClient.postMultipart(
      ApiEndpoints.customerExtractPaymentProof(token),
      fileFieldName: 'file',
      filename: filename,
      fileBytes: fileBytes,
      timeout: const Duration(seconds: 60),
    );
    if (response is Map<String, dynamic>) {
      return response;
    }
    return {};
  }

  Future<Map<String, dynamic>> submitPaymentProof({
    required String token,
    required String stepKey,
    String? payeeAccount,
    String? payerAccount,
    String? transactionId,
    double? amount,
    String? currency,
    String? paymentStatus,
    String? paymentMethod,
    Uint8List? fileBytes,
    String? filename,
  }) async {
    final fields = <String, String>{
      'workflow_step_key': stepKey,
      if (payeeAccount != null && payeeAccount.isNotEmpty)
        'payee_account': payeeAccount,
      if (payerAccount != null && payerAccount.isNotEmpty)
        'payer_account': payerAccount,
      if (transactionId != null && transactionId.isNotEmpty)
        'transaction_id': transactionId,
      if (amount != null) 'amount': amount.toString(),
      if (currency != null && currency.isNotEmpty) 'currency': currency,
      if (paymentStatus != null && paymentStatus.isNotEmpty)
        'payment_status': paymentStatus,
      if (paymentMethod != null && paymentMethod.isNotEmpty)
        'payment_method': paymentMethod,
    };
    final response = await _apiClient.postMultipart(
      ApiEndpoints.customerSubmitPaymentProof(token),
      fileFieldName: 'file',
      filename: filename ?? 'payment_proof.jpg',
      fileBytes: fileBytes,
      fields: fields,
    );
    if (response is Map<String, dynamic>) {
      return response;
    }
    return {};
  }
}

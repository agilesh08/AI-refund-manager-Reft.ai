/// Evidence submission and adaptive follow-up request models.
class EvidenceResponseModel {
  final String id;
  final String verificationSessionId;
  final String evidenceType;
  final String? originalFilename;
  final String? storedFilename;
  final String? mimeType;
  final int? fileSizeBytes;
  final String? sha256Hash;
  final bool isDuplicate;
  final String? textContent;
  final String? workflowStepKey;
  final DateTime? createdAt;

  EvidenceResponseModel({
    required this.id,
    required this.verificationSessionId,
    required this.evidenceType,
    this.originalFilename,
    this.storedFilename,
    this.mimeType,
    this.fileSizeBytes,
    this.sha256Hash,
    this.isDuplicate = false,
    this.textContent,
    this.workflowStepKey,
    this.createdAt,
  });

  factory EvidenceResponseModel.fromJson(Map<String, dynamic> json) {
    final rawId = (json['id'] ?? json['evidence_id'] ?? '').toString();
    return EvidenceResponseModel(
      id: rawId,
      verificationSessionId: json['verification_session_id'] as String? ?? '',
      evidenceType: json['evidence_type'] as String? ?? 'CUSTOMER_IMAGE',
      originalFilename: json['original_filename'] as String?,
      storedFilename: json['stored_filename'] as String?,
      mimeType: json['mime_type'] as String?,
      fileSizeBytes: (json['file_size_bytes'] as num?)?.toInt(),
      sha256Hash: json['sha256_hash'] as String?,
      isDuplicate: json['is_duplicate'] as bool? ?? false,
      textContent: json['text_content'] as String?,
      workflowStepKey: json['workflow_step_key'] as String?,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
    );
  }
}

class CustomerEvidenceRequestModel {
  final String id;
  final String? verificationSessionId;
  final String requestedStepKey;
  final String requestedEvidenceType;
  final String promptText;
  final String? reason;
  final List<String> options;
  final String status;
  final DateTime? createdAt;
  final DateTime? fulfilledAt;

  CustomerEvidenceRequestModel({
    required this.id,
    this.verificationSessionId,
    required this.requestedStepKey,
    this.requestedEvidenceType = 'CUSTOMER_IMAGE',
    required this.promptText,
    this.reason,
    this.options = const [],
    required this.status,
    this.createdAt,
    this.fulfilledAt,
  });

  bool get isPending => status.toUpperCase() == 'PENDING';
  bool get isFulfilled => status.toUpperCase() == 'FULFILLED';
  String get workflowStepKey => requestedStepKey;

  factory CustomerEvidenceRequestModel.fromJson(Map<String, dynamic> json) {
    final rawOptions = json['options'] ?? json['options_json'];
    final List<String> optsList = (rawOptions is List)
        ? rawOptions.map((e) => e.toString()).toList()
        : [];

    final rawType = (json['requested_evidence_type'] ?? 'CUSTOMER_IMAGE').toString().toUpperCase();
    String normalizedType = 'CUSTOMER_IMAGE';
    if (rawType.contains('MCQ') || rawType.contains('CHOICE')) {
      normalizedType = 'MCQ';
    } else if (rawType.contains('TEXT')) {
      normalizedType = 'TEXT';
    }

    return CustomerEvidenceRequestModel(
      id: json['id'] as String? ?? '',
      verificationSessionId: json['verification_session_id'] as String?,
      requestedStepKey: json['workflow_step_key'] as String? ??
          json['step_key'] as String? ??
          json['requested_step_key'] as String? ??
          '',
      requestedEvidenceType: normalizedType,
      promptText: json['reason'] as String? ??
          json['prompt_text'] as String? ??
          'Please provide additional evidence.',
      reason: json['reason'] as String?,
      options: optsList,
      status: json['status'] as String? ?? 'PENDING',
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
      fulfilledAt: json['fulfilled_at'] != null
          ? DateTime.tryParse(json['fulfilled_at'].toString())
          : null,
    );
  }
}

class EvidenceFulfillResult {
  final CustomerEvidenceRequestModel request;
  final EvidenceResponseModel evidence;
  final String? reasoningAction;
  final String? nextStepKey;
  final String message;

  EvidenceFulfillResult({
    required this.request,
    required this.evidence,
    this.reasoningAction,
    this.nextStepKey,
    required this.message,
  });

  factory EvidenceFulfillResult.fromJson(Map<String, dynamic> json) {
    return EvidenceFulfillResult(
      request: CustomerEvidenceRequestModel.fromJson(
        (json['request'] as Map<String, dynamic>?) ?? {},
      ),
      evidence: EvidenceResponseModel.fromJson(
        (json['evidence'] as Map<String, dynamic>?) ?? {},
      ),
      reasoningAction: json['reasoning_action'] as String?,
      nextStepKey: json['next_step_key'] as String?,
      message: json['message'] as String? ?? 'Evidence uploaded successfully',
    );
  }
}

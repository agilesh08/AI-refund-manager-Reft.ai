/// Evidence Fusion assessment models (sanitized customer view & merchant detail view).
class CustomerFusionModel {
  final String verificationId;
  final String status;
  final String message;
  final String? assessmentSummary;
  final String? nextSteps;
  final int submittedEvidenceCount;
  final int pendingRequestsCount;

  CustomerFusionModel({
    required this.verificationId,
    required this.status,
    required this.message,
    this.assessmentSummary,
    this.nextSteps,
    this.submittedEvidenceCount = 0,
    this.pendingRequestsCount = 0,
  });

  factory CustomerFusionModel.fromJson(Map<String, dynamic> json) {
    return CustomerFusionModel(
      verificationId: json['verification_id'] as String? ?? '',
      status: (json['status_display'] ?? json['status'] ?? json['assessment_state'] ?? '') as String,
      message: (json['customer_summary'] ?? json['message'] ?? 'Review in progress') as String,
      assessmentSummary: (json['customer_summary'] ?? json['assessment_summary']) as String?,
      nextSteps: json['next_steps'] as String?,
      submittedEvidenceCount:
          (json['submitted_evidence_count'] as num?)?.toInt() ?? 0,
      pendingRequestsCount:
          (json['pending_requests_count'] as num?)?.toInt() ?? 0,
    );
  }
}

class FusionResponseModel {
  final String id;
  final String verificationSessionId;
  final String assessmentState;
  final double overallConfidence;
  final List<dynamic> rulesEvaluated;
  final List<dynamic> contradictions;
  final List<dynamic> missingEvidence;
  final Map<String, dynamic> explanation;
  final String? fusionVersion;
  final DateTime? createdAt;

  FusionResponseModel({
    required this.id,
    required this.verificationSessionId,
    required this.assessmentState,
    required this.overallConfidence,
    this.rulesEvaluated = const [],
    this.contradictions = const [],
    this.missingEvidence = const [],
    this.explanation = const {},
    this.fusionVersion,
    this.createdAt,
  });

  factory FusionResponseModel.fromJson(Map<String, dynamic> json) {
    return FusionResponseModel(
      id: json['id'] as String? ?? '',
      verificationSessionId: json['verification_session_id'] as String? ?? '',
      assessmentState:
          json['assessment_state'] as String? ?? 'REVIEW_REQUIRED',
      overallConfidence: (json['overall_confidence'] as num?)?.toDouble() ?? 0.0,
      rulesEvaluated: json['rules_evaluated'] as List<dynamic>? ?? [],
      contradictions: json['contradictions'] as List<dynamic>? ?? [],
      missingEvidence: json['missing_evidence'] as List<dynamic>? ?? [],
      explanation: (json['explanation'] as Map<String, dynamic>?) ?? {},
      fusionVersion: json['fusion_version'] as String?,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
    );
  }
}

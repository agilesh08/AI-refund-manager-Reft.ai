import 'evidence_models.dart';
import 'fusion_models.dart';
import 'merchant_decision_models.dart';
import 'signal_models.dart';

/// Timeline audit event model.
class TimelineItemModel {
  final DateTime timestamp;
  final String eventType;
  final String title;
  final String description;
  final String source; // SYSTEM, CUSTOMER, MERCHANT, GEMINI_VISION, LLAMA_REASONING, EXTERNAL_SIGNAL
  final Map<String, dynamic> metadata;

  TimelineItemModel({
    required this.timestamp,
    required this.eventType,
    required this.title,
    required this.description,
    required this.source,
    this.metadata = const {},
  });

  factory TimelineItemModel.fromJson(Map<String, dynamic> json) {
    return TimelineItemModel(
      timestamp: json['timestamp'] != null
          ? (DateTime.tryParse(json['timestamp'].toString()) ?? DateTime.now())
          : DateTime.now(),
      eventType: json['event_type'] as String? ?? 'EVENT',
      title: json['title'] as String? ?? 'Timeline Event',
      description: json['description'] as String? ?? '',
      source: json['source'] as String? ?? 'SYSTEM',
      metadata: (json['metadata'] as Map<String, dynamic>?) ?? {},
    );
  }
}

/// Lightweight dashboard verification summary card item.
class DashboardVerificationItemModel {
  final String verificationId;
  final String orderId;
  final String? productName;
  final double? refundAmount;
  final String status;
  final String? assessmentState;
  final double? confidence;
  final String? customerId;
  final String? customerEmail;
  final String? refundReason;
  final String? latestDecision;
  final int evidenceCount;
  final DateTime? heldAt;
  final DateTime? holdUntil;
  final String? heldBy;
  final DateTime createdAt;

  DashboardVerificationItemModel({
    required this.verificationId,
    required this.orderId,
    this.productName,
    this.refundAmount,
    required this.status,
    this.assessmentState,
    this.confidence,
    this.customerId,
    this.customerEmail,
    this.refundReason,
    this.latestDecision,
    this.evidenceCount = 0,
    this.heldAt,
    this.holdUntil,
    this.heldBy,
    required this.createdAt,
  });

  bool get isHeld => status == 'HELD';

  factory DashboardVerificationItemModel.fromJson(Map<String, dynamic> json) {
    return DashboardVerificationItemModel(
      verificationId: json['verification_id'] as String? ?? json['id'] as String? ?? '',
      orderId: json['order_id'] as String? ?? '',
      productName: json['product_name'] as String?,
      refundAmount: (json['refund_amount'] as num?)?.toDouble(),
      status: json['status'] as String? ?? 'CREATED',
      assessmentState: json['assessment_state'] as String? ??
          json['latest_assessment_state'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      customerId: json['customer_id'] as String?,
      customerEmail: json['customer_email'] as String?,
      refundReason: json['refund_reason'] as String?,
      latestDecision: json['latest_decision'] as String?,
      evidenceCount: (json['evidence_count'] as num?)?.toInt() ?? 0,
      heldAt: json['held_at'] != null
          ? DateTime.tryParse(json['held_at'].toString())
          : null,
      holdUntil: json['hold_until'] != null
          ? DateTime.tryParse(json['hold_until'].toString())
          : null,
      heldBy: json['held_by'] as String?,
      createdAt: json['created_at'] != null
          ? (DateTime.tryParse(json['created_at'].toString()) ?? DateTime.now())
          : DateTime.now(),
    );
  }
}

/// Paginated dashboard response.
class DashboardVerificationListModel {
  final List<DashboardVerificationItemModel> items;
  final int page;
  final int pageSize;
  final int total;

  DashboardVerificationListModel({
    required this.items,
    this.page = 1,
    this.pageSize = 20,
    this.total = 0,
  });

  factory DashboardVerificationListModel.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List<dynamic>? ?? [];
    return DashboardVerificationListModel(
      items: rawItems
          .map((i) => DashboardVerificationItemModel.fromJson(
              i as Map<String, dynamic>))
          .toList(),
      page: (json['page'] as num?)?.toInt() ?? 1,
      pageSize: (json['page_size'] as num?)?.toInt() ?? 20,
      total: (json['total'] as num?)?.toInt() ?? 0,
    );
  }
}

/// 9-Section Explainable Final Verification Report.
class ExplainableVerificationReportModel {
  final String verificationId;
  final String assessmentState;
  final double overallConfidence;

  // 9 Structured Sections
  final Map<String, dynamic> executiveSummary;
  final Map<String, dynamic> consistencyAssessment;
  final Map<String, dynamic> visualConsistencyFindings;
  final Map<String, dynamic> signalVerificationFindings;
  final Map<String, dynamic> multiSourceFusionMatrix;
  final Map<String, dynamic> claimVsEvidenceReconciliation;
  final Map<String, dynamic> missingEvidenceAndFollowUp;
  final Map<String, dynamic> merchantDecisionContext;
  final Map<String, dynamic> aiAuditTrail;

  // Full Investigation Trail & Recommendation
  final List<Map<String, dynamic>> questionsAsked;
  final List<Map<String, dynamic>> adaptiveFollowUpQuestions;
  final Map<String, dynamic> visualFindingsCategorized;
  final Map<String, String> deterministicSignalStatuses;
  final String? recommendationCode;
  final String? recommendationLabel;

  ExplainableVerificationReportModel({
    required this.verificationId,
    required this.assessmentState,
    required this.overallConfidence,
    required this.executiveSummary,
    required this.consistencyAssessment,
    required this.visualConsistencyFindings,
    required this.signalVerificationFindings,
    required this.multiSourceFusionMatrix,
    required this.claimVsEvidenceReconciliation,
    required this.missingEvidenceAndFollowUp,
    required this.merchantDecisionContext,
    required this.aiAuditTrail,
    this.questionsAsked = const [],
    this.adaptiveFollowUpQuestions = const [],
    this.visualFindingsCategorized = const {},
    this.deterministicSignalStatuses = const {},
    this.recommendationCode,
    this.recommendationLabel,
  });

  factory ExplainableVerificationReportModel.fromJson(
      Map<String, dynamic> json) {
    final rawQs = json['questions_asked'] as List<dynamic>? ?? [];
    final rawAdaptive = json['adaptive_follow_up_questions'] as List<dynamic>? ?? [];
    final rawSignals = (json['deterministic_signal_statuses'] as Map<String, dynamic>?) ?? {};

    return ExplainableVerificationReportModel(
      verificationId: json['verification_id'] as String? ?? '',
      assessmentState:
          json['assessment_state'] as String? ?? 'REVIEW_REQUIRED',
      overallConfidence:
          (json['overall_confidence'] as num?)?.toDouble() ?? 0.0,
      executiveSummary:
          (json['executive_summary'] as Map<String, dynamic>?) ?? {},
      consistencyAssessment:
          (json['consistency_assessment'] as Map<String, dynamic>?) ?? {},
      visualConsistencyFindings:
          (json['visual_consistency_findings'] as Map<String, dynamic>?) ?? {},
      signalVerificationFindings:
          (json['signal_verification_findings'] as Map<String, dynamic>?) ?? {},
      multiSourceFusionMatrix:
          (json['multi_source_fusion_matrix'] as Map<String, dynamic>?) ?? {},
      claimVsEvidenceReconciliation:
          (json['claim_vs_evidence_reconciliation'] as Map<String, dynamic>?) ??
              {},
      missingEvidenceAndFollowUp:
          (json['missing_evidence_and_follow_up'] as Map<String, dynamic>?) ??
              {},
      merchantDecisionContext:
          (json['merchant_decision_context'] as Map<String, dynamic>?) ?? {},
      aiAuditTrail: (json['ai_audit_trail'] as Map<String, dynamic>?) ?? {},
      questionsAsked: rawQs.map((e) => e as Map<String, dynamic>).toList(),
      adaptiveFollowUpQuestions: rawAdaptive.map((e) => e as Map<String, dynamic>).toList(),
      visualFindingsCategorized:
          (json['visual_findings_categorized'] as Map<String, dynamic>?) ?? {},
      deterministicSignalStatuses:
          rawSignals.map((k, v) => MapEntry(k.toString(), v.toString())),
      recommendationCode: json['recommendation_code'] as String?,
      recommendationLabel: json['recommendation_label'] as String?,
    );
  }
}

/// Unified 13-Facet Merchant Investigation Detail View.
class VerificationDetailDashboardModel {
  final Map<String, dynamic> verification;
  final Map<String, dynamic> product;
  final Map<String, dynamic> claim;
  final Map<String, dynamic> workflow;
  final Map<String, dynamic> evidenceSummary;
  final List<EvidenceResponseModel> evidenceItems;
  final Map<String, dynamic> visualAnalysisSummary;
  final List<Map<String, dynamic>> visualAnalysisItems;
  final Map<String, dynamic> signalsSummary;
  final List<SignalItemModel> signalItems;
  final List<CustomerEvidenceRequestModel> adaptiveRequests;
  final FusionResponseModel? fusionResult;
  final Map<String, dynamic>? llamaReasoning;
  final List<TimelineItemModel> timeline;
  final MerchantDecisionModel? merchantDecision;
  final List<MerchantDecisionModel> decisions;
  final ExplainableVerificationReportModel? report;

  // Full Investigation Trail & Recommendation
  final List<Map<String, dynamic>> questionsAsked;
  final List<Map<String, dynamic>> adaptiveFollowUpQuestions;
  final Map<String, dynamic> visualFindingsCategorized;
  final Map<String, String> deterministicSignalStatuses;
  final String? recommendationCode;
  final String? recommendationLabel;

  VerificationDetailDashboardModel({
    required this.verification,
    required this.product,
    required this.claim,
    required this.workflow,
    this.evidenceSummary = const {},
    this.evidenceItems = const [],
    this.visualAnalysisSummary = const {},
    this.visualAnalysisItems = const [],
    this.signalsSummary = const {},
    this.signalItems = const [],
    this.adaptiveRequests = const [],
    this.fusionResult,
    this.llamaReasoning,
    this.timeline = const [],
    this.merchantDecision,
    this.decisions = const [],
    this.report,
    this.questionsAsked = const [],
    this.adaptiveFollowUpQuestions = const [],
    this.visualFindingsCategorized = const {},
    this.deterministicSignalStatuses = const {},
    this.recommendationCode,
    this.recommendationLabel,
  });

  String get verificationId =>
      verification['verification_id'] as String? ??
      verification['id'] as String? ??
      '';
  String get orderId =>
      claim['order_id'] as String? ??
      verification['order_id'] as String? ??
      '';
  String get status => verification['status'] as String? ?? 'CREATED';
  bool get isHeld => status == 'HELD';
  DateTime? get heldAt => verification['held_at'] != null
      ? DateTime.tryParse(verification['held_at'].toString())
      : null;
  DateTime? get holdUntil => verification['hold_until'] != null
      ? DateTime.tryParse(verification['hold_until'].toString())
      : null;
  String? get heldBy => verification['held_by'] as String?;

  String? get assessmentState =>
      fusionResult?.assessmentState ??
      verification['latest_assessment_state'] as String? ??
      verification['assessment_state'] as String?;

  factory VerificationDetailDashboardModel.fromJson(Map<String, dynamic> json) {
    final rawEvItems = json['evidence_items'] as List<dynamic>? ??
        json['evidence'] as List<dynamic>? ??
        [];
    final parsedEvItems = rawEvItems
        .map((e) => EvidenceResponseModel.fromJson(e as Map<String, dynamic>))
        .toList();

    final rawSignals = json['signal_items'] as List<dynamic>? ??
        json['signals'] as List<dynamic>? ??
        [];
    final parsedSignals = rawSignals
        .map((s) => SignalItemModel.fromJson(s as Map<String, dynamic>))
        .toList();

    final rawAdaptive = json['adaptive_requests'] as List<dynamic>? ?? [];
    final parsedAdaptive = rawAdaptive
        .map((a) =>
            CustomerEvidenceRequestModel.fromJson(a as Map<String, dynamic>))
        .toList();

    final rawTimeline = json['timeline'] as List<dynamic>? ?? [];
    final parsedTimeline = rawTimeline
        .map((t) => TimelineItemModel.fromJson(t as Map<String, dynamic>))
        .toList();

    final rawDecisions = json['decisions'] as List<dynamic>? ?? [];
    final parsedDecisions = rawDecisions
        .map((d) => MerchantDecisionModel.fromJson(d as Map<String, dynamic>))
        .toList();

    MerchantDecisionModel? singleDecision;
    if (json['merchant_decision'] != null) {
      singleDecision = MerchantDecisionModel.fromJson(
          json['merchant_decision'] as Map<String, dynamic>);
    } else if (parsedDecisions.isNotEmpty) {
      singleDecision = parsedDecisions.first;
    }

    FusionResponseModel? parsedFusion;
    final rawFusion = json['fusion_result'] ?? json['fusion'];
    if (rawFusion is Map<String, dynamic>) {
      parsedFusion = FusionResponseModel.fromJson(rawFusion);
    }

    ExplainableVerificationReportModel? parsedReport;
    if (json['report'] is Map<String, dynamic>) {
      parsedReport = ExplainableVerificationReportModel.fromJson(
          json['report'] as Map<String, dynamic>);
    }

    final rawVisual = json['visual_analysis_items'] as List<dynamic>? ??
        json['visual_analysis'] as List<dynamic>? ??
        [];
    final parsedVisual = rawVisual.map((v) => v as Map<String, dynamic>).toList();

    final rawQs = json['questions_asked'] as List<dynamic>? ?? [];
    final parsedQs = rawQs.isNotEmpty
        ? rawQs.map((e) => e as Map<String, dynamic>).toList()
        : (parsedReport?.questionsAsked ?? []);

    final rawAdaptiveQs = json['adaptive_follow_up_questions'] as List<dynamic>? ?? [];
    final parsedAdaptiveQs = rawAdaptiveQs.isNotEmpty
        ? rawAdaptiveQs.map((e) => e as Map<String, dynamic>).toList()
        : (parsedReport?.adaptiveFollowUpQuestions ?? []);

    final visualCat = (json['visual_findings_categorized'] as Map<String, dynamic>?) ??
        parsedReport?.visualFindingsCategorized ??
        {};

    final sigStatusesRaw = (json['deterministic_signal_statuses'] as Map<String, dynamic>?) ?? {};
    final sigStatuses = sigStatusesRaw.isNotEmpty
        ? sigStatusesRaw.map((k, v) => MapEntry(k.toString(), v.toString()))
        : (parsedReport?.deterministicSignalStatuses ?? {});

    final recCode = json['recommendation_code'] as String? ?? parsedReport?.recommendationCode;
    final recLabel = json['recommendation_label'] as String? ?? parsedReport?.recommendationLabel;

    return VerificationDetailDashboardModel(
      verification: (json['verification'] as Map<String, dynamic>?) ?? {},
      product: (json['product'] as Map<String, dynamic>?) ?? {},
      claim: (json['claim'] as Map<String, dynamic>?) ?? {},
      workflow: (json['workflow'] as Map<String, dynamic>?) ?? {},
      evidenceSummary:
          (json['evidence_summary'] as Map<String, dynamic>?) ?? {},
      evidenceItems: parsedEvItems,
      visualAnalysisSummary:
          (json['visual_analysis_summary'] as Map<String, dynamic>?) ?? {},
      visualAnalysisItems: parsedVisual,
      signalsSummary: (json['signals_summary'] as Map<String, dynamic>?) ?? {},
      signalItems: parsedSignals,
      adaptiveRequests: parsedAdaptive,
      fusionResult: parsedFusion,
      llamaReasoning: (json['llama_reasoning'] as Map<String, dynamic>?) ??
          (json['reasoning'] as Map<String, dynamic>?),
      timeline: parsedTimeline,
      merchantDecision: singleDecision,
      decisions: parsedDecisions,
      report: parsedReport,
      questionsAsked: parsedQs,
      adaptiveFollowUpQuestions: parsedAdaptiveQs,
      visualFindingsCategorized: visualCat,
      deterministicSignalStatuses: sigStatuses,
      recommendationCode: recCode,
      recommendationLabel: recLabel,
    );
  }
}

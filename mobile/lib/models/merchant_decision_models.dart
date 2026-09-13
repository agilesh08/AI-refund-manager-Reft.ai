/// Human merchant refund decision models.
class MerchantDecisionCreate {
  final String decision; // REFUND_APPROVED, REFUND_REJECTED, MANUAL_REVIEW
  final String? notes;
  final String? decisionReason;
  final List<String>? rejectionReasons;
  final String? actionTaken;

  MerchantDecisionCreate({
    required this.decision,
    this.notes,
    this.decisionReason,
    this.rejectionReasons,
    this.actionTaken,
  });

  Map<String, dynamic> toJson() {
    final map = <String, dynamic>{
      'decision': decision,
    };
    if (notes != null && notes!.isNotEmpty) {
      map['notes'] = notes;
      map['decision_reason'] = notes;
    } else if (decisionReason != null && decisionReason!.isNotEmpty) {
      map['decision_reason'] = decisionReason;
      map['notes'] = decisionReason;
    }
    if (rejectionReasons != null && rejectionReasons!.isNotEmpty) {
      map['rejection_reasons'] = rejectionReasons;
    }
    if (actionTaken != null && actionTaken!.isNotEmpty) {
      map['action_taken'] = actionTaken;
    }
    return map;
  }
}

class MerchantDecisionModel {
  final String id;
  final String? decisionId;
  final String verificationSessionId;
  final String merchantId;
  final String decision;
  final String? decisionReason;
  final String? notes;
  final List<String> rejectionReasons;
  final String? actionTaken;
  final DateTime? decidedAt;
  final DateTime? createdAt;

  MerchantDecisionModel({
    required this.id,
    this.decisionId,
    required this.verificationSessionId,
    required this.merchantId,
    required this.decision,
    this.decisionReason,
    this.notes,
    this.rejectionReasons = const [],
    this.actionTaken,
    this.decidedAt,
    this.createdAt,
  });

  factory MerchantDecisionModel.fromJson(Map<String, dynamic> json) {
    final rawRejections = json['rejection_reasons'];
    List<String> rejections = [];
    if (rawRejections is List) {
      rejections = rawRejections.map((e) => e.toString()).toList();
    }

    return MerchantDecisionModel(
      id: json['id'] as String? ?? json['decision_id'] as String? ?? '',
      decisionId: json['decision_id'] as String? ?? json['id'] as String?,
      verificationSessionId:
          json['verification_session_id'] as String? ?? '',
      merchantId: json['merchant_id'] as String? ?? '',
      decision: json['decision'] as String? ?? '',
      decisionReason: json['decision_reason'] as String?,
      notes: json['notes'] as String? ?? json['decision_reason'] as String?,
      rejectionReasons: rejections,
      actionTaken: json['action_taken'] as String?,
      decidedAt: json['decided_at'] != null
          ? DateTime.tryParse(json['decided_at'].toString())
          : null,
      createdAt: json['created_at'] != null
          ? DateTime.tryParse(json['created_at'].toString())
          : null,
    );
  }
}

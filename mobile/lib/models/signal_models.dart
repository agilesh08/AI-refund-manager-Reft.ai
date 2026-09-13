/// Deterministic transaction signal models (Payment, Order, Delivery, Location).
class CustomerSignalModel {
  final String id;
  final String signalType;
  final String sourceType;
  final String status;
  final DateTime? observedAt;
  final Map<String, dynamic> summary;

  CustomerSignalModel({
    required this.id,
    required this.signalType,
    required this.sourceType,
    required this.status,
    this.observedAt,
    this.summary = const {},
  });

  factory CustomerSignalModel.fromJson(Map<String, dynamic> json) {
    return CustomerSignalModel(
      id: json['id'] as String? ?? '',
      signalType: json['signal_type'] as String? ?? '',
      sourceType: json['source_type'] as String? ?? '',
      status: json['status'] as String? ?? '',
      observedAt: json['observed_at'] != null
          ? DateTime.tryParse(json['observed_at'].toString())
          : null,
      summary: (json['summary'] as Map<String, dynamic>?) ??
          (json['data'] as Map<String, dynamic>?) ??
          {},
    );
  }
}

class SignalItemModel {
  final String id;
  final String signalType;
  final String sourceType;
  final String? sourceReference;
  final String status;
  final double? confidence;
  final DateTime? observedAt;
  final Map<String, dynamic> data;

  SignalItemModel({
    required this.id,
    required this.signalType,
    required this.sourceType,
    this.sourceReference,
    required this.status,
    this.confidence,
    this.observedAt,
    this.data = const {},
  });

  factory SignalItemModel.fromJson(Map<String, dynamic> json) {
    return SignalItemModel(
      id: json['id'] as String? ?? '',
      signalType: json['signal_type'] as String? ?? '',
      sourceType: json['source_type'] as String? ?? '',
      sourceReference: json['source_reference'] as String?,
      status: json['status'] as String? ?? '',
      confidence: (json['confidence'] as num?)?.toDouble(),
      observedAt: json['observed_at'] != null
          ? DateTime.tryParse(json['observed_at'].toString())
          : null,
      data: (json['data'] as Map<String, dynamic>?) ?? {},
    );
  }
}

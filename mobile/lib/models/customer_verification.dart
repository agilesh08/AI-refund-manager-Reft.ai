/// Models representing public customer verification views.
class CustomerMerchantInfo {
  final String businessName;
  final String? supportEmail;

  CustomerMerchantInfo({
    required this.businessName,
    this.supportEmail,
  });

  factory CustomerMerchantInfo.fromJson(Map<String, dynamic> json) {
    return CustomerMerchantInfo(
      businessName: json['business_name'] as String? ?? 'Merchant',
      supportEmail: json['support_email'] as String?,
    );
  }
}

class CustomerProductInfo {
  final String name;
  final String? sku;
  final String? brand;
  final String? category;

  CustomerProductInfo({
    required this.name,
    this.sku,
    this.brand,
    this.category,
  });

  factory CustomerProductInfo.fromJson(Map<String, dynamic> json) {
    return CustomerProductInfo(
      name: json['name'] as String? ?? 'Product',
      sku: json['sku'] as String?,
      brand: json['brand'] as String?,
      category: json['category'] as String?,
    );
  }
}

class CustomerWorkflowInfo {
  final String workflowName;
  final int totalSteps;

  CustomerWorkflowInfo({
    required this.workflowName,
    required this.totalSteps,
  });

  factory CustomerWorkflowInfo.fromJson(Map<String, dynamic> json) {
    return CustomerWorkflowInfo(
      workflowName: json['workflow_name'] as String? ?? 'Verification Workflow',
      totalSteps: (json['total_steps'] as num?)?.toInt() ?? 0,
    );
  }
}

class CustomerVerificationResponse {
  final String verificationId;
  final CustomerMerchantInfo merchant;
  final CustomerProductInfo product;
  final String status;
  final DateTime? expiresAt;
  final CustomerWorkflowInfo workflow;

  CustomerVerificationResponse({
    required this.verificationId,
    required this.merchant,
    required this.product,
    required this.status,
    this.expiresAt,
    required this.workflow,
  });

  factory CustomerVerificationResponse.fromJson(Map<String, dynamic> json) {
    return CustomerVerificationResponse(
      verificationId: json['verification_id'] as String? ?? '',
      merchant: CustomerMerchantInfo.fromJson(
        (json['merchant'] as Map<String, dynamic>?) ?? {},
      ),
      product: CustomerProductInfo.fromJson(
        (json['product'] as Map<String, dynamic>?) ?? {},
      ),
      status: json['status'] as String? ?? 'CREATED',
      expiresAt: json['expires_at'] != null
          ? DateTime.tryParse(json['expires_at'].toString())
          : null,
      workflow: CustomerWorkflowInfo.fromJson(
        (json['workflow'] as Map<String, dynamic>?) ?? {},
      ),
    );
  }
}

class VerificationStartResponse {
  final String verificationId;
  final String status;
  final DateTime? startedAt;
  final String message;

  VerificationStartResponse({
    required this.verificationId,
    required this.status,
    this.startedAt,
    required this.message,
  });

  factory VerificationStartResponse.fromJson(Map<String, dynamic> json) {
    return VerificationStartResponse(
      verificationId: json['verification_id'] as String? ?? '',
      status: json['status'] as String? ?? 'IN_PROGRESS',
      startedAt: json['started_at'] != null
          ? DateTime.tryParse(json['started_at'].toString())
          : null,
      message: json['message'] as String? ?? '',
    );
  }
}

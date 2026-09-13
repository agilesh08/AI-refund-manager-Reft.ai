import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../../core/constants/app_colors.dart';
import '../../core/network/api_exception.dart';
import '../../services/merchant_service.dart';

/// Screen allowing merchants to create and dispatch a new verification session.
class CreateVerificationScreen extends StatefulWidget {
  const CreateVerificationScreen({super.key});

  @override
  State<CreateVerificationScreen> createState() =>
      _CreateVerificationScreenState();
}

class _CreateVerificationScreenState extends State<CreateVerificationScreen> {
  final _formKey = GlobalKey<FormState>();
  final MerchantService _merchantService = MerchantService();
  final ImagePicker _picker = ImagePicker();

  final TextEditingController _orderIdController = TextEditingController();
  final TextEditingController _customerNameController =
      TextEditingController();
  final TextEditingController _customerContactController =
      TextEditingController();
  final TextEditingController _refundReasonController =
      TextEditingController();
  final TextEditingController _refundAmountController =
      TextEditingController();

  List<Map<String, dynamic>> _products = [];
  List<Map<String, dynamic>> _workflows = [];
  final Map<String, Map<String, dynamic>> _completenessMap = {};
  String? _selectedProductId;
  String? _selectedWorkflowId;
  int _maxAttempts = 1;

  bool _isLoadingData = true;
  bool _isSubmitting = false;
  String? _loadError;

  @override
  void initState() {
    super.initState();
    _fetchDependencies();
  }

  @override
  void dispose() {
    _orderIdController.dispose();
    _customerNameController.dispose();
    _customerContactController.dispose();
    _refundReasonController.dispose();
    _refundAmountController.dispose();
    super.dispose();
  }

  Future<void> _fetchDependencies() async {
    setState(() {
      _isLoadingData = true;
      _loadError = null;
    });

    try {
      final results = await Future.wait([
        _merchantService.listProducts(),
        _merchantService.listWorkflows(),
      ]);

      final products = results[0];
      final workflows = results[1];

      final completenessResults = await Future.wait(
        products.map((p) async {
          final pId = p['id']?.toString() ?? '';
          if (pId.isEmpty) return null;
          try {
            final comp = await _merchantService.getProductCompleteness(pId);
            return MapEntry(pId, comp);
          } catch (_) {
            return null;
          }
        }),
      );

      final compMap = <String, Map<String, dynamic>>{};
      for (final entry in completenessResults) {
        if (entry != null) {
          compMap[entry.key] = entry.value;
        }
      }

      setState(() {
        _products = products;
        _workflows = workflows;
        _completenessMap.addAll(compMap);
        if (_products.isNotEmpty) {
          _selectedProductId = _products.first['id']?.toString();
        }
        if (_workflows.isNotEmpty) {
          _selectedWorkflowId = _workflows.first['id']?.toString();
        }
        _isLoadingData = false;
      });
    } catch (e) {
      setState(() {
        _isLoadingData = false;
        if (e is ApiException) {
          _loadError = e.userMessage;
        } else {
          _loadError = 'Failed to load products or workflows. Please try again.';
        }
      });
    }
  }

  Widget _buildProductDetailsCard() {
    if (_selectedProductId == null) return const SizedBox.shrink();
    final product = _products.firstWhere(
      (p) => p['id']?.toString() == _selectedProductId,
      orElse: () => {},
    );
    if (product.isEmpty) return const SizedBox.shrink();

    final sku = product['sku'] ?? 'N/A';
    final price = product['price'];
    final comp = _completenessMap[_selectedProductId];
    final isComplete = comp?['complete'] == true || comp?['is_complete'] == true;
    final int count = (comp?['existing_count'] is int)
        ? comp!['existing_count'] as int
        : (isComplete
            ? 4
            : (comp?['missing_angles'] is List
                ? (4 - (comp!['missing_angles'] as List).length).clamp(0, 4)
                : 0));

    return Container(
      margin: const EdgeInsets.only(top: 8, bottom: 14),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: isComplete
            ? AppColors.assessmentConsistentBg.withValues(alpha: 0.5)
            : AppColors.assessmentReviewRequiredBg.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: isComplete
              ? AppColors.assessmentConsistent.withValues(alpha: 0.35)
              : AppColors.assessmentReviewRequired.withValues(alpha: 0.35),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'SKU: $sku',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.darkNeutral,
                ),
              ),
              if (price != null)
                Text(
                  '₹${price.toString()}',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: AppColors.primary,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Icon(
                isComplete
                    ? Icons.check_circle_rounded
                    : Icons.warning_amber_rounded,
                size: 14,
                color: isComplete
                    ? AppColors.assessmentConsistent
                    : AppColors.assessmentReviewRequired,
              ),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  isComplete
                      ? 'Trusted Reference: Ready for Visual Verification (4/4 angles)'
                      : 'Trusted Reference: Incomplete ($count/4 angles) — AI visual verification will have reduced confidence.',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: isComplete
                        ? AppColors.assessmentConsistent
                        : AppColors.assessmentReviewRequired,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _showImportOrderDialog() {
    final textController = TextEditingController();
    final messenger = ScaffoldMessenger.of(context);
    bool dialogLoading = false;
    String? dialogError;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => StatefulBuilder(
        builder: (ctx, setModalState) => Container(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 24,
          ),
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.auto_awesome, color: AppColors.primary, size: 20),
                        SizedBox(width: 8),
                        Text(
                          'Import Order Details',
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ],
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 20),
                      onPressed: () => Navigator.of(sheetContext).pop(),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                const Text(
                  'Auto-fill fields from an order screenshot or pasted text snippet.',
                  style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
                ),
                const SizedBox(height: 16),
                if (dialogError != null)
                  Container(
                    margin: const EdgeInsets.only(bottom: 12),
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: AppColors.assessmentInconsistentBg,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                          color: AppColors.assessmentInconsistent
                              .withValues(alpha: 0.3)),
                    ),
                    child: Text(
                      dialogError!,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.assessmentInconsistent),
                    ),
                  ),
                if (dialogLoading)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Center(
                      child: Column(
                        children: [
                          CircularProgressIndicator(strokeWidth: 2.5),
                          SizedBox(height: 12),
                          Text(
                            'Extracting order details with AI...',
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: AppColors.darkNeutral,
                            ),
                          ),
                        ],
                      ),
                    ),
                  )
                else ...[
                  OutlinedButton.icon(
                    icon: const Icon(Icons.image_outlined, size: 20),
                    label: const Text('Upload Order Screenshot / Receipt'),
                    style: OutlinedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 13),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                    onPressed: () async {
                      try {
                        final picked = await _picker.pickImage(
                            source: ImageSource.gallery);
                        if (picked == null) return;
                        setModalState(() {
                          dialogLoading = true;
                          dialogError = null;
                        });
                        final bytes = await picked.readAsBytes();
                        final extracted = await _merchantService.extractOrder(
                          imageBytes: bytes,
                          filename: picked.name,
                        );
                        _applyExtractedOrder(extracted);
                        if (sheetContext.mounted) {
                          Navigator.of(sheetContext).pop();
                        }
                        messenger.showSnackBar(
                          const SnackBar(
                            content: Text(
                                'Order details successfully extracted and applied.'),
                            backgroundColor: AppColors.assessmentConsistent,
                          ),
                        );
                      } catch (e) {
                        setModalState(() {
                          dialogLoading = false;
                          dialogError = e is ApiException
                              ? e.userMessage
                              : 'Failed to extract from screenshot.';
                        });
                      }
                    },
                  ),
                  const SizedBox(height: 14),
                  const Row(
                    children: [
                      Expanded(child: Divider()),
                      Padding(
                        padding: EdgeInsets.symmetric(horizontal: 10),
                        child: Text('OR',
                            style: TextStyle(
                                fontSize: 11,
                                color: AppColors.textMuted,
                                fontWeight: FontWeight.w700)),
                      ),
                      Expanded(child: Divider()),
                    ],
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: textController,
                    maxLines: 4,
                    decoration: InputDecoration(
                      hintText:
                          'Paste order confirmation text, receipt snippet, or invoice...',
                      hintStyle: const TextStyle(fontSize: 12.5),
                      contentPadding: const EdgeInsets.all(12),
                      border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  ElevatedButton.icon(
                    icon: const Icon(Icons.bolt_rounded, size: 18),
                    label: const Text('Extract from Text'),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10)),
                    ),
                    onPressed: () async {
                      final txt = textController.text.trim();
                      if (txt.isEmpty) {
                        setModalState(() =>
                            dialogError = 'Please paste some order text first.');
                        return;
                      }
                      setModalState(() {
                        dialogLoading = true;
                        dialogError = null;
                      });
                      try {
                        final extracted =
                            await _merchantService.extractOrder(text: txt);
                        _applyExtractedOrder(extracted);
                        if (sheetContext.mounted) {
                          Navigator.of(sheetContext).pop();
                        }
                        messenger.showSnackBar(
                          const SnackBar(
                            content: Text(
                                'Order details successfully extracted and applied.'),
                            backgroundColor: AppColors.assessmentConsistent,
                          ),
                        );
                      } catch (e) {
                        setModalState(() {
                          dialogLoading = false;
                          dialogError = e is ApiException
                              ? e.userMessage
                              : 'Failed to extract from text.';
                        });
                      }
                    },
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _applyExtractedOrder(Map<String, dynamic> extracted) {
    if (extracted.isEmpty) return;
    setState(() {
      // 1. Order ID (preserve manual input, support aliases)
      final orderId = extracted['order_id'] ??
          extracted['orderId'] ??
          extracted['order_number'] ??
          extracted['order_no'];
      if (_orderIdController.text.trim().isEmpty &&
          orderId != null &&
          orderId.toString().trim().isNotEmpty) {
        _orderIdController.text = orderId.toString().trim();
      }

      // 2. Customer Name (preserve manual input, support aliases)
      final custName = extracted['customer_name'] ??
          extracted['customerName'] ??
          extracted['name'] ??
          extracted['buyer_name'] ??
          extracted['buyer'] ??
          extracted['recipient_name'] ??
          extracted['recipient'] ??
          extracted['full_name'];
      if (_customerNameController.text.trim().isEmpty &&
          custName != null &&
          custName.toString().trim().isNotEmpty) {
        _customerNameController.text = custName.toString().trim();
      }

      // 3. Customer Contact (preserve manual input, support email/phone aliases)
      final contact = extracted['customer_contact'] ??
          extracted['customerContact'] ??
          extracted['customer_email'] ??
          extracted['email'] ??
          extracted['customer_phone'] ??
          extracted['phone'] ??
          extracted['contact'] ??
          extracted['mobile'];
      if (_customerContactController.text.trim().isEmpty &&
          contact != null &&
          contact.toString().trim().isNotEmpty) {
        _customerContactController.text = contact.toString().trim();
      }

      // 4. Refund Reason (preserve manual input, support aliases)
      final reason = extracted['refund_reason'] ??
          extracted['refundReason'] ??
          extracted['reported_issue'] ??
          extracted['reason'] ??
          extracted['issue'] ??
          extracted['defect'];
      if (_refundReasonController.text.trim().isEmpty &&
          reason != null &&
          reason.toString().trim().isNotEmpty) {
        _refundReasonController.text = reason.toString().trim();
      }

      // 5. Refund Amount (preserve manual input, support aliases)
      final amt = extracted['refund_amount'] ??
          extracted['refundAmount'] ??
          extracted['order_amount'] ??
          extracted['orderAmount'] ??
          extracted['amount'] ??
          extracted['total'];
      if (_refundAmountController.text.trim().isEmpty &&
          amt != null &&
          amt.toString().trim().isNotEmpty) {
        _refundAmountController.text = amt.toString().trim();
      }

      // 6. Product Match (only auto-select if no product is currently selected)
      if (_selectedProductId == null) {
        final sku = (extracted['sku'] ?? '').toString().toLowerCase().trim();
        final pName = (extracted['product_name'] ??
                extracted['product'] ??
                extracted['item'] ??
                extracted['item_name'] ??
                '')
            .toString()
            .toLowerCase()
            .trim();
        for (final p in _products) {
          final prodSku = (p['sku'] ?? '').toString().toLowerCase().trim();
          final prodName = (p['name'] ?? '').toString().toLowerCase().trim();
          if (sku.isNotEmpty &&
              prodSku.isNotEmpty &&
              (prodSku == sku || prodSku.contains(sku) || sku.contains(prodSku))) {
            _selectedProductId = p['id']?.toString();
            break;
          }
          if (pName.isNotEmpty &&
              prodName.isNotEmpty &&
              (prodName == pName ||
                  prodName.contains(pName) ||
                  pName.contains(prodName))) {
            _selectedProductId = p['id']?.toString();
            break;
          }
        }
      }
    });
  }

  Widget _buildVerificationConfigCard() {
    if (_selectedWorkflowId == null) return const SizedBox.shrink();
    final wf = _workflows.firstWhere(
      (w) => w['id']?.toString() == _selectedWorkflowId,
      orElse: () => {},
    );
    if (wf.isEmpty) return const SizedBox.shrink();

    final rawSteps = wf['steps'];
    final List<dynamic> stepsList = (rawSteps is List) ? rawSteps : [];

    final hasPayment = stepsList.any((s) {
      final type = s['step_type']?.toString().toUpperCase();
      final cfg = s['config'] ?? s['config_json'] ?? {};
      final enabled = (cfg is Map && cfg['enabled'] == false) ? false : true;
      return type == 'PAYMENT' && enabled;
    });

    final hasOrder = stepsList.any((s) {
      final type = s['step_type']?.toString().toUpperCase();
      final cfg = s['config'] ?? s['config_json'] ?? {};
      final enabled = (cfg is Map && cfg['enabled'] == false) ? false : true;
      return type == 'ORDER' && enabled;
    });

    final hasDelivery = stepsList.any((s) {
      final type = s['step_type']?.toString().toUpperCase();
      final cfg = s['config'] ?? s['config_json'] ?? {};
      final enabled = (cfg is Map && cfg['enabled'] == false) ? false : true;
      return type == 'DELIVERY' && enabled;
    });

    final rules = [
      {'title': 'Initial Evidence', 'detail': 'Customer capture (max 3)', 'enabled': true},
      {'title': 'Visual Analysis', 'detail': 'Visual AI', 'enabled': true},
      {'title': 'Adaptive Follow-up', 'detail': 'Targeted AI inquiry', 'enabled': true},
      {
        'title': 'Payment verification',
        'detail': hasPayment ? 'Recipient matching' : 'Disabled',
        'enabled': hasPayment,
      },
      {
        'title': 'Order verification',
        'detail': hasOrder ? 'Record cross-reference' : 'Disabled',
        'enabled': hasOrder,
      },
      {
        'title': 'Delivery verification',
        'detail': hasDelivery ? 'Package check' : 'Disabled',
        'enabled': hasDelivery,
      },
    ];

    return Container(
      margin: const EdgeInsets.only(top: 8, bottom: 14),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border, width: 0.9),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: AppColors.primaryLight.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Icon(Icons.tune_rounded, size: 14, color: AppColors.primary),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Active Verification Rules (${wf['name'] ?? 'Selected Workflow'})',
                  style: const TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.darkNeutral,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          const Divider(height: 1),
          const SizedBox(height: 8),
          ...rules.map((r) {
            final isEnabled = r['enabled'] as bool;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text(
                      r['title'] as String,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w500,
                        color: isEnabled ? AppColors.darkNeutral : AppColors.textMuted,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        isEnabled
                            ? Icons.check_circle_rounded
                            : Icons.remove_circle_outline_rounded,
                        size: 13,
                        color: isEnabled
                            ? AppColors.assessmentConsistent
                            : AppColors.textMuted,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        r['detail'] as String,
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                          color: isEnabled
                              ? AppColors.assessmentConsistent
                              : AppColors.textMuted,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_selectedProductId == null || _selectedProductId!.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select a product')),
      );
      return;
    }

    final selectedProduct = _products.firstWhere(
      (p) => p['id']?.toString() == _selectedProductId,
      orElse: () => {},
    );
    final status = selectedProduct['reference_processing_status']?.toString() ?? 'NOT_READY';
    if (status == 'PROCESSING') {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('This product is still being prepared for visual verification. Please wait until reference analysis is complete.'),
          backgroundColor: AppColors.assessmentReviewRequired,
        ),
      );
      return;
    }

    if (_selectedWorkflowId == null || _selectedWorkflowId!.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please select a verification workflow')),
      );
      return;
    }

    setState(() => _isSubmitting = true);

    try {
      double? amount;
      final amountText = _refundAmountController.text.trim();
      if (amountText.isNotEmpty) {
        amount = double.tryParse(amountText);
      }

      final session = await _merchantService.createVerificationSession(
        productId: _selectedProductId!,
        workflowId: _selectedWorkflowId!,
        orderId: _orderIdController.text.trim(),
        customerName: _customerNameController.text.trim(),
        customerContact: _customerContactController.text.trim(),
        refundReason: _refundReasonController.text.trim(),
        refundAmount: amount,
        maxAttempts: _maxAttempts,
      );

      if (mounted) {
        context.pushReplacement('/verification-created', extra: session);
      }
    } catch (e) {
      if (mounted) {
        String msg = 'Failed to create verification session.';
        if (e is ApiException) {
          msg = e.userMessage;
        }
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(msg),
            backgroundColor: AppColors.assessmentInconsistent,
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: 'Back to Dashboard',
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/dashboard');
            }
          },
        ),
        title: const Text('Create Verification'),
      ),
      body: _isLoadingData
          ? const Center(child: CircularProgressIndicator())
          : _loadError != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline,
                            size: 48, color: AppColors.assessmentInconsistent),
                        const SizedBox(height: 12),
                        Text(
                          _loadError!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                              fontSize: 14, color: AppColors.textSecondary),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton.icon(
                          onPressed: _fetchDependencies,
                          icon: const Icon(Icons.refresh),
                          label: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                )
              : SingleChildScrollView(
                  padding: const EdgeInsets.all(18),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        // Subtitle & Header context
                        const Text(
                          'Create Verification',
                          style: TextStyle(
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                            color: AppColors.darkNeutral,
                            letterSpacing: -0.3,
                          ),
                        ),
                        const SizedBox(height: 3),
                        const Text(
                          'Set up a secure verification for a customer refund claim.',
                          style: TextStyle(
                            fontSize: 12.5,
                            color: AppColors.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 16),

                        // SECTION 1: Customer & Order
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            _buildSectionHeader('1. Customer & Order', Icons.person_outline_rounded),
                            InkWell(
                              onTap: _showImportOrderDialog,
                              borderRadius: BorderRadius.circular(8),
                              child: Container(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                                decoration: BoxDecoration(
                                  color: AppColors.primary.withValues(alpha: 0.1),
                                  borderRadius: BorderRadius.circular(8),
                                  border: Border.all(color: AppColors.primary.withValues(alpha: 0.25)),
                                ),
                                child: const Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(Icons.auto_awesome, size: 14, color: AppColors.primary),
                                    SizedBox(width: 4),
                                    Text(
                                      'Import Order',
                                      style: TextStyle(
                                        fontSize: 11.5,
                                        fontWeight: FontWeight.w700,
                                        color: AppColors.primary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        TextFormField(
                          controller: _orderIdController,
                          decoration: const InputDecoration(
                            labelText: 'Order ID *',
                            hintText: 'e.g. ORD-2026-9921',
                            prefixIcon: Icon(Icons.receipt_outlined, size: 20),
                          ),
                          validator: (val) {
                            if (val == null || val.trim().isEmpty) {
                              return 'Order ID is required';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _customerNameController,
                          decoration: const InputDecoration(
                            labelText: 'Customer Name',
                            hintText: 'e.g. Rahul Sharma',
                            prefixIcon: Icon(Icons.badge_outlined, size: 20),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _customerContactController,
                          decoration: const InputDecoration(
                            labelText: 'Customer Contact',
                            hintText: 'e.g. customer@example.com or phone',
                            prefixIcon: Icon(Icons.contact_mail_outlined, size: 20),
                          ),
                        ),
                        const SizedBox(height: 20),

                        // SECTION 2: Product
                        _buildSectionHeader('2. Product', Icons.shopping_bag_outlined),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          initialValue: _selectedProductId,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Select Product *',
                            prefixIcon: Icon(Icons.inventory_2_outlined, size: 20),
                          ),
                          items: _products.map((p) {
                            final name = p['name'] ?? 'Product';
                            final sku = p['sku'] != null ? ' (${p['sku']})' : '';
                            final status = p['reference_processing_status']?.toString() ?? 'NOT_READY';
                            String prefix = '✓ ';
                            if (status == 'PROCESSING') {
                              prefix = '⏳ ';
                            } else if (status == 'FAILED' || status == 'NOT_READY') {
                              prefix = '⚠ ';
                            }
                            return DropdownMenuItem<String>(
                              value: p['id']?.toString(),
                              child: Text(
                                '$prefix$name$sku',
                                overflow: TextOverflow.ellipsis,
                              ),
                            );
                          }).toList(),
                          onChanged: (val) =>
                              setState(() => _selectedProductId = val),
                          validator: (val) => (val == null || val.isEmpty)
                              ? 'Please select a product'
                              : null,
                        ),
                        _buildProductDetailsCard(),
                        const SizedBox(height: 14),

                        // SECTION 3: Refund Claim
                        _buildSectionHeader('3. Refund Claim', Icons.receipt_long_outlined),
                        const SizedBox(height: 8),
                        TextFormField(
                          controller: _refundAmountController,
                          keyboardType: const TextInputType.numberWithOptions(
                              decimal: true),
                          decoration: const InputDecoration(
                            labelText: 'Refund Amount (₹)',
                            hintText: '0.00',
                            prefixIcon: Icon(Icons.currency_rupee_rounded, size: 20),
                          ),
                          validator: (val) {
                            if (val != null && val.trim().isNotEmpty) {
                              final num = double.tryParse(val.trim());
                              if (num == null || num <= 0) {
                                return 'Enter a valid amount greater than 0';
                              }
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          controller: _refundReasonController,
                          maxLines: 2,
                          decoration: const InputDecoration(
                            labelText: 'Refund Reason / Customer Claim',
                            hintText: 'e.g. Broken screen on delivery',
                            prefixIcon: Icon(Icons.comment_outlined, size: 20),
                          ),
                        ),
                        const SizedBox(height: 20),

                        // SECTION 4: Verification Configuration
                        _buildSectionHeader('4. Verification Configuration', Icons.verified_outlined),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          initialValue: _selectedWorkflowId,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Verification Workflow *',
                            prefixIcon: Icon(Icons.account_tree_outlined, size: 20),
                          ),
                          items: _workflows.map((w) {
                            final name = w['name'] ?? 'Workflow';
                            final isDefault = w['is_default'] == true
                                ? ' (Default)'
                                : '';
                            return DropdownMenuItem<String>(
                              value: w['id']?.toString(),
                              child: Text(
                                '$name$isDefault',
                                overflow: TextOverflow.ellipsis,
                              ),
                            );
                          }).toList(),
                          onChanged: (val) =>
                              setState(() => _selectedWorkflowId = val),
                          validator: (val) => (val == null || val.isEmpty)
                              ? 'Please select a workflow'
                              : null,
                        ),
                        _buildVerificationConfigCard(),
                        DropdownButtonFormField<int>(
                          initialValue: _maxAttempts,
                          isExpanded: true,
                          decoration: const InputDecoration(
                            labelText: 'Max Submission Attempts',
                            helperText:
                                'Locks session once completed or limit reached',
                            prefixIcon: Icon(Icons.lock_clock_outlined, size: 20),
                          ),
                          items: const [
                            DropdownMenuItem(
                              value: 1,
                              child: Text(
                                '1 Attempt (Recommended)',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            DropdownMenuItem(
                              value: 2,
                              child: Text(
                                '2 Attempts',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            DropdownMenuItem(
                              value: 3,
                              child: Text(
                                '3 Attempts',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            DropdownMenuItem(
                              value: 5,
                              child: Text(
                                '5 Attempts',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                          onChanged: (val) {
                            if (val != null) setState(() => _maxAttempts = val);
                          },
                        ),
                        const SizedBox(height: 26),

                        // Submit & Cancel Buttons
                        ElevatedButton(
                          onPressed: _isSubmitting ? null : _submit,
                          child: _isSubmitting
                              ? const SizedBox(
                                  height: 20,
                                  width: 20,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white),
                                )
                              : const Text(
                                  'Generate Verification Session',
                                ),
                        ),
                        const SizedBox(height: 10),
                        OutlinedButton(
                          onPressed: _isSubmitting
                              ? null
                              : () {
                                  if (context.canPop()) {
                                    context.pop();
                                  } else {
                                    context.go('/dashboard');
                                  }
                                },
                          child: const Text('Cancel'),
                        ),
                      ],
                    ),
                  ),
                ),
    );
  }

  Widget _buildSectionHeader(String title, IconData icon) {
    return Row(
      children: [
        Icon(icon, size: 16, color: AppColors.primary),
        const SizedBox(width: 6),
        Text(
          title,
          style: const TextStyle(
            fontSize: 13.5,
            fontWeight: FontWeight.w700,
            color: AppColors.darkNeutral,
            letterSpacing: -0.1,
          ),
        ),
      ],
    );
  }
}

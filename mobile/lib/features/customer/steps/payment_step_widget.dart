import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../../../core/constants/app_colors.dart';
import '../../../core/network/api_exception.dart';
import '../../../models/workflow_step.dart';
import '../../../services/customer_verification_service.dart';

/// Payment verification dynamic workflow step widget with proof upload & AI extraction.
class PaymentStepWidget extends StatefulWidget {
  final WorkflowStepItem step;
  final String? token;
  final String? initialValue;
  final ValueChanged<String> onChanged;
  final void Function(Map<String, dynamic> data, Uint8List? imageBytes, String? filename)?
      onPaymentConfirmed;

  const PaymentStepWidget({
    super.key,
    required this.step,
    this.token,
    this.initialValue,
    required this.onChanged,
    this.onPaymentConfirmed,
  });

  @override
  State<PaymentStepWidget> createState() => _PaymentStepWidgetState();
}

class _PaymentStepWidgetState extends State<PaymentStepWidget> {
  final ImagePicker _picker = ImagePicker();
  final CustomerVerificationService _service = CustomerVerificationService();

  final TextEditingController _upiController = TextEditingController();
  final TextEditingController _txnController = TextEditingController();
  final TextEditingController _amountController = TextEditingController();
  final TextEditingController _dateController = TextEditingController();
  final TextEditingController _statusController =
      TextEditingController(text: 'SUCCESS');

  Uint8List? _proofImageBytes;
  String? _proofImageFilename;
  bool _isExtracting = false;
  String? _extractError;
  bool _isConfirmed = false;
  bool? _accountMatched;
  String? _expectedPayee;

  @override
  void initState() {
    super.initState();
    if (widget.initialValue != null && widget.initialValue!.isNotEmpty) {
      _parseInitialValue(widget.initialValue!);
    }
  }

  void _parseInitialValue(String value) {
    // Attempt basic extraction if structured
    final parts = value.split(' | ');
    for (final p in parts) {
      if (p.startsWith('UPI/Account: ')) {
        _upiController.text = p.replaceFirst('UPI/Account: ', '');
      } else if (p.startsWith('Txn ID: ')) {
        _txnController.text = p.replaceFirst('Txn ID: ', '');
      } else if (p.startsWith('Amount: ₹')) {
        _amountController.text = p.replaceFirst('Amount: ₹', '');
      } else if (p.startsWith('Date: ')) {
        _dateController.text = p.replaceFirst('Date: ', '');
      } else if (p.startsWith('Status: ')) {
        _statusController.text = p.replaceFirst('Status: ', '');
      }
    }
    if (_upiController.text.isNotEmpty || _txnController.text.isNotEmpty) {
      _isConfirmed = true;
    }
  }

  @override
  void dispose() {
    _upiController.dispose();
    _txnController.dispose();
    _amountController.dispose();
    _dateController.dispose();
    _statusController.dispose();
    super.dispose();
  }

  void _notify() {
    final upi = _upiController.text.trim();
    final txn = _txnController.text.trim();
    final amt = _amountController.text.trim();
    final date = _dateController.text.trim();
    final status = _statusController.text.trim();

    final parts = <String>[];
    if (upi.isNotEmpty) parts.add('UPI/Account: $upi');
    if (txn.isNotEmpty) parts.add('Txn ID: $txn');
    if (amt.isNotEmpty) parts.add('Amount: ₹$amt');
    if (date.isNotEmpty) parts.add('Date: $date');
    if (status.isNotEmpty) parts.add('Status: $status');

    final summary = parts.isNotEmpty
        ? parts.join(' | ')
        : 'Payment details pending confirmation';
    widget.onChanged(summary);
  }

  Future<void> _pickPaymentProof() async {
    try {
      final photo = await _picker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 90,
        maxWidth: 1920,
        maxHeight: 1920,
      );
      if (photo == null) return;

      final bytes = await photo.readAsBytes();
      setState(() {
        _proofImageBytes = bytes;
        _proofImageFilename = photo.name;
        _isExtracting = true;
        _extractError = null;
        _isConfirmed = false;
      });

      if (widget.token != null && widget.token!.isNotEmpty) {
        final result = await _service.extractPaymentProof(
          token: widget.token!,
          fileBytes: bytes,
          filename: photo.name,
        );

        if (result['extracted'] is Map<String, dynamic>) {
          final ext = Map<String, dynamic>.from(result['extracted'] as Map);
          setState(() {
            if (ext['payee_account'] != null &&
                (ext['payee_account'] as String).isNotEmpty) {
              _upiController.text = ext['payee_account'].toString();
            } else if (ext['upi_id'] != null &&
                (ext['upi_id'] as String).isNotEmpty) {
              _upiController.text = ext['upi_id'].toString();
            }
            if (ext['transaction_id'] != null &&
                (ext['transaction_id'] as String).isNotEmpty) {
              _txnController.text = ext['transaction_id'].toString();
            }
            if (ext['amount'] != null) {
              _amountController.text = ext['amount'].toString();
            }
            if (ext['date'] != null && (ext['date'] as String).isNotEmpty) {
              _dateController.text = ext['date'].toString();
            }
            if (ext['status'] != null &&
                (ext['status'] as String).isNotEmpty) {
              _statusController.text = ext['status'].toString();
            }
            _accountMatched = result['account_matched'] as bool?;
            _expectedPayee = result['expected_payee'] as String?;
          });
          final data = <String, dynamic>{
            'payee_account': _upiController.text.trim(),
            'payer_account': null,
            'transaction_id': _txnController.text.trim(),
            'amount': _amountController.text.trim(),
            'date': _dateController.text.trim(),
            'status': _statusController.text.trim(),
            'payment_status': _statusController.text.trim(),
          };
          widget.onPaymentConfirmed
              ?.call(data, _proofImageBytes, _proofImageFilename);
        }
      }
      _notify();
    } catch (e) {
      setState(() {
        _extractError = e is ApiException
            ? e.userMessage
            : 'Could not automatically extract details. You can enter them manually below.';
      });
    } finally {
      if (mounted) {
        setState(() => _isExtracting = false);
      }
    }
  }

  void _confirmDetails() {
    setState(() => _isConfirmed = true);
    _notify();
    final data = <String, dynamic>{
      'payee_account': _upiController.text.trim(),
      'payer_account': null,
      'transaction_id': _txnController.text.trim(),
      'amount': _amountController.text.trim(),
      'date': _dateController.text.trim(),
      'status': _statusController.text.trim(),
      'payment_status': _statusController.text.trim(),
    };
    widget.onPaymentConfirmed
        ?.call(data, _proofImageBytes, _proofImageFilename);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Payment details confirmed.'),
        backgroundColor: AppColors.assessmentConsistent,
        duration: Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.step.description != null &&
            widget.step.description!.isNotEmpty) ...[
          Text(
            widget.step.description!,
            style: const TextStyle(
              fontSize: 13.5,
              color: AppColors.textSecondary,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 14),
        ],

        // Security Notice Banner
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.primaryLight.withValues(alpha: 0.35),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
                color: AppColors.primary.withValues(alpha: 0.2)),
          ),
          child: const Row(
            children: [
              Icon(Icons.security_rounded,
                  size: 18, color: AppColors.primary),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Zero-Trust Privacy: Reft.AI only checks payment proof authenticity. We never ask for, process, or store OTP, PIN, CVV, or card passwords.',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: AppColors.darkNeutral,
                    height: 1.3,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),

        // Section: Payment Proof Upload
        const Text(
          'Upload Payment Proof Screenshot',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppColors.darkNeutral,
          ),
        ),
        const SizedBox(height: 4),
        const Text(
          'Upload your UPI app receipt, bank statement entry, or payment confirmation screen.',
          style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
        ),
        const SizedBox(height: 10),

        if (_proofImageBytes != null) ...[
          Container(
            height: 160,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.border),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Stack(
                fit: StackFit.expand,
                children: [
                  Image.memory(
                    _proofImageBytes!,
                    fit: BoxFit.cover,
                    cacheHeight: 320,
                  ),
                  Positioned(
                    top: 8,
                    right: 8,
                    child: CircleAvatar(
                      backgroundColor: Colors.black54,
                      radius: 16,
                      child: IconButton(
                        icon: const Icon(Icons.refresh_rounded,
                            size: 16, color: Colors.white),
                        tooltip: 'Change Screenshot',
                        onPressed: _pickPaymentProof,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (_proofImageFilename != null)
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 8),
              child: Text(
                _proofImageFilename!,
                style: const TextStyle(
                    fontSize: 11, color: AppColors.textSecondary),
              ),
            ),
          const SizedBox(height: 12),
        ] else ...[
          OutlinedButton.icon(
            onPressed: _isExtracting ? null : _pickPaymentProof,
            icon: const Icon(Icons.upload_file_rounded, size: 20),
            label: const Text('Select Payment Proof Screenshot'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10)),
            ),
          ),
          const SizedBox(height: 12),
        ],

        if (_isExtracting) ...[
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: Center(
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(width: 12),
                  Text(
                    'Extracting payment metadata with AI...',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                      color: AppColors.darkNeutral,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],

        if (_extractError != null) ...[
          Container(
            padding: const EdgeInsets.all(10),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: AppColors.assessmentReviewRequiredBg,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                  color: AppColors.assessmentReviewRequired
                      .withValues(alpha: 0.3)),
            ),
            child: Row(
              children: [
                const Icon(Icons.info_outline,
                    size: 16, color: AppColors.assessmentReviewRequired),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _extractError!,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: AppColors.darkNeutral,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],

        // Payee match status badge if matched
        if (_accountMatched != null) ...[
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: _accountMatched!
                  ? AppColors.assessmentConsistentBg
                  : AppColors.assessmentReviewRequiredBg,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: _accountMatched!
                    ? AppColors.assessmentConsistent.withValues(alpha: 0.35)
                    : AppColors.assessmentReviewRequired
                        .withValues(alpha: 0.35),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  _accountMatched!
                      ? Icons.check_circle_rounded
                      : Icons.warning_amber_rounded,
                  size: 16,
                  color: _accountMatched!
                      ? AppColors.assessmentConsistent
                      : AppColors.assessmentReviewRequired,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _accountMatched!
                        ? 'Payee Account Matched Merchant Record${_expectedPayee != null ? " ($_expectedPayee)" : ""}'
                        : 'Payee Account requires manual review${_expectedPayee != null ? " (Expected: $_expectedPayee)" : ""}',
                    style: TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w700,
                      color: _accountMatched!
                          ? AppColors.assessmentConsistent
                          : AppColors.assessmentReviewRequired,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],

        // Reviewable Extracted Fields
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    'Review Payment Details',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: AppColors.darkNeutral,
                    ),
                  ),
                  if (_isConfirmed)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: AppColors.assessmentConsistentBg,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.check_circle_rounded,
                              size: 12,
                              color: AppColors.assessmentConsistent),
                          SizedBox(width: 4),
                          Text(
                            'Confirmed',
                            style: TextStyle(
                              fontSize: 10.5,
                              fontWeight: FontWeight.w700,
                              color: AppColors.assessmentConsistent,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _upiController,
                decoration: const InputDecoration(
                  labelText: 'UPI ID / Payee Account',
                  hintText: 'e.g. merchant@upi',
                  prefixIcon:
                      Icon(Icons.account_balance_wallet_outlined, size: 18),
                ),
                onChanged: (_) {
                  setState(() => _isConfirmed = false);
                  _notify();
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _txnController,
                decoration: const InputDecoration(
                  labelText: 'Transaction ID / UTR',
                  hintText: 'e.g. 429104819024',
                  prefixIcon: Icon(Icons.receipt_long_outlined, size: 18),
                ),
                onChanged: (_) {
                  setState(() => _isConfirmed = false);
                  _notify();
                },
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _amountController,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      decoration: const InputDecoration(
                        labelText: 'Paid Amount (₹)',
                        hintText: '0.00',
                        prefixIcon:
                            Icon(Icons.currency_rupee_rounded, size: 18),
                      ),
                      onChanged: (_) {
                        setState(() => _isConfirmed = false);
                        _notify();
                      },
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextField(
                      controller: _dateController,
                      decoration: const InputDecoration(
                        labelText: 'Payment Date',
                        hintText: 'DD/MM/YYYY',
                        prefixIcon:
                            Icon(Icons.calendar_today_outlined, size: 18),
                      ),
                      onChanged: (_) {
                        setState(() => _isConfirmed = false);
                        _notify();
                      },
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              ElevatedButton.icon(
                onPressed: _confirmDetails,
                icon: const Icon(Icons.check_rounded, size: 18),
                label: const Text('Confirm Payment Details'),
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  backgroundColor: _isConfirmed
                      ? AppColors.assessmentConsistent
                      : AppColors.primary,
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

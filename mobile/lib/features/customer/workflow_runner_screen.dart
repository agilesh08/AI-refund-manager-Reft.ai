import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../models/workflow_step.dart';
import '../../state/customer_flow_provider.dart';
import 'adaptive_request_sheet.dart';
import 'steps/delivery_step_widget.dart';
import 'steps/image_step_widget.dart';
import 'steps/mcq_step_widget.dart';
import 'steps/order_step_widget.dart';
import 'steps/payment_step_widget.dart';
import 'steps/text_step_widget.dart';

/// Customer workflow step runner iterating through frozen workflow steps.
class WorkflowRunnerScreen extends StatefulWidget {
  final String token;

  const WorkflowRunnerScreen({super.key, required this.token});

  @override
  State<WorkflowRunnerScreen> createState() => _WorkflowRunnerScreenState();
}

class _WorkflowRunnerScreenState extends State<WorkflowRunnerScreen> {
  String? _currentText;
  Uint8List? _currentImageBytes;
  String? _currentImageFilename;
  final List<Uint8List> _capturedImages = [];
  final List<String> _capturedFilenames = [];
  Map<String, dynamic>? _paymentData;
  Uint8List? _paymentImageBytes;
  String? _paymentImageFilename;
  bool _isSubmittingStep = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<CustomerFlowProvider>();
      if (provider.overview?.status == 'COMPLETED') {
        context.go('/verify/${widget.token}');
        return;
      }
      if (provider.steps.isEmpty) {
        provider.loadSession(widget.token);
      }
    });
  }

  void _clearStepState() {
    setState(() {
      _currentText = null;
      _currentImageBytes = null;
      _currentImageFilename = null;
      _capturedImages.clear();
      _capturedFilenames.clear();
      _paymentData = null;
      _paymentImageBytes = null;
      _paymentImageFilename = null;
    });
  }

  Future<void> _submitCurrentStep(
      CustomerFlowProvider provider, WorkflowStepItem step) async {
    if (_isSubmittingStep || provider.isSubmitting) return;

    final isImageStep =
        step.stepType == 'IMAGE' || step.stepType == 'CAMERA';
    final isPaymentStep = step.stepType == 'PAYMENT';

    if (step.required) {
      if (isImageStep && _currentImageBytes == null && _capturedImages.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please capture or select an image.')),
        );
        return;
      } else if (isPaymentStep &&
          _paymentData == null &&
          (_currentText == null || _currentText!.trim().isEmpty)) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please upload payment proof and confirm details.')),
        );
        return;
      } else if (!isImageStep &&
          !isPaymentStep &&
          (_currentText == null || _currentText!.trim().isEmpty)) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please answer the required question.')),
        );
        return;
      }
    }

    setState(() {
      _isSubmittingStep = true;
    });

    try {
      bool success;
      if (isPaymentStep) {
        final amt = _paymentData != null && _paymentData!['amount'] != null
            ? double.tryParse(_paymentData!['amount'].toString())
            : null;
        success = await provider.submitPaymentProof(
          stepKey: step.stepKey,
          payeeAccount: _paymentData?['payee_account']?.toString(),
          payerAccount: _paymentData?['payer_account']?.toString(),
          transactionId: _paymentData?['transaction_id']?.toString(),
          amount: amt,
          currency: 'INR',
          paymentStatus: _paymentData?['payment_status']?.toString() ?? 'PAID',
          paymentMethod: 'UPI',
          fileBytes: _paymentImageBytes,
          filename: _paymentImageFilename,
        );
      } else {
        final primaryBytes = _capturedImages.isNotEmpty
            ? _capturedImages.first
            : _currentImageBytes;
        final primaryFilename = _capturedFilenames.isNotEmpty
            ? _capturedFilenames.first
            : _currentImageFilename;
        final additionalBytes = _capturedImages.length > 1
            ? _capturedImages.sublist(1)
            : null;
        final additionalNames = _capturedFilenames.length > 1
            ? _capturedFilenames.sublist(1)
            : null;

        success = await provider.submitStepEvidence(
          stepKey: step.stepKey,
          stepType: step.stepType,
          textContent: _currentText,
          imageBytes: primaryBytes,
          filename: primaryFilename,
          additionalImages: additionalBytes,
          additionalFilenames: additionalNames,
        );
      }

      if (!success) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(provider.errorMessage ?? 'Submission failed.'),
            ),
          );
        }
        return;
      }

      // Check if there are adaptive follow-up requests triggered
      await provider.checkAdaptiveRequests();
      if (provider.hasPendingAdaptiveRequests && mounted) {
        final pending =
            provider.adaptiveRequests.firstWhere((r) => r.isPending);
        _showAdaptiveSheet(context, provider, pending);
        return;
      }

      // Advance to next step or complete
      if (provider.currentStepIndex < provider.steps.length - 1) {
        _clearStepState();
        provider.nextStep();
      } else {
        // All steps finished
        if (mounted) {
          final token = widget.token.trim().isNotEmpty
              ? widget.token.trim()
              : (provider.token?.trim().isNotEmpty == true
                  ? provider.token!.trim()
                  : '');
          if (token.isNotEmpty) {
            context.go('/verify/$token/reviewing');
          } else {
            context.go('/');
          }
        }
      }
    } finally {
      if (mounted) {
        setState(() {
          _isSubmittingStep = false;
        });
      }
    }
  }

  void _showAdaptiveSheet(BuildContext context,
      CustomerFlowProvider provider, dynamic request) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => AdaptiveRequestSheet(
        request: request,
        isSubmitting: provider.isSubmitting,
        onFulfill: (reqId, bytes, name) async {
          final ok = await provider.fulfillAdaptiveRequest(
            requestId: reqId,
            imageBytes: bytes,
            filename: name,
          );
          if (ok && ctx.mounted) {
            Navigator.pop(ctx);
            if (provider.currentStepIndex >= provider.steps.length - 1) {
              if (context.mounted) {
                final token = widget.token.trim().isNotEmpty
                    ? widget.token.trim()
                    : (provider.token?.trim().isNotEmpty == true
                        ? provider.token!.trim()
                        : '');
                if (token.isNotEmpty) {
                  context.go('/verify/$token/reviewing');
                } else {
                  context.go('/');
                }
              }
            } else {
              _clearStepState();
              provider.nextStep();
            }
          }
        },
      ),
    );
  }

  Widget _buildStepWidget(WorkflowStepItem step) {
    switch (step.stepType) {
      case 'MCQ':
        return McqStepWidget(
          step: step,
          selectedValue: _currentText,
          onSelected: (val) => setState(() => _currentText = val),
        );
      case 'IMAGE':
      case 'CAMERA':
        return ImageStepWidget(
          step: step,
          selectedImageBytes: _currentImageBytes,
          filename: _currentImageFilename,
          initialImages: _capturedImages.isNotEmpty ? _capturedImages : null,
          initialFilenames:
              _capturedFilenames.isNotEmpty ? _capturedFilenames : null,
          onImagePicked: (bytes, name) {
            setState(() {
              _currentImageBytes = bytes;
              _currentImageFilename = name;
            });
          },
          onImagesChanged: (images, filenames) {
            setState(() {
              _capturedImages.clear();
              _capturedImages.addAll(images);
              _capturedFilenames.clear();
              _capturedFilenames.addAll(filenames);
              if (images.isNotEmpty) {
                _currentImageBytes = images.first;
                _currentImageFilename = filenames.first;
              } else {
                _currentImageBytes = null;
                _currentImageFilename = null;
              }
            });
          },
          onImageRemoved: () {
            setState(() {
              _currentImageBytes = null;
              _currentImageFilename = null;
              _capturedImages.clear();
              _capturedFilenames.clear();
            });
          },
        );
      case 'PAYMENT':
        return PaymentStepWidget(
          step: step,
          token: widget.token,
          initialValue: _currentText,
          onChanged: (val) => _currentText = val,
          onPaymentConfirmed: (data, imageBytes, filename) {
            setState(() {
              _paymentData = data;
              _paymentImageBytes = imageBytes;
              _paymentImageFilename = filename;
              _currentText = 'PAYMENT_CONFIRMED';
            });
          },
        );
      case 'ORDER':
        return OrderStepWidget(
          step: step,
          initialValue: _currentText,
          onChanged: (val) => _currentText = val,
        );
      case 'DELIVERY':
        return DeliveryStepWidget(
          step: step,
          initialValue: _currentText,
          onChanged: (val) => _currentText = val,
        );
      case 'TEXT':
      default:
        return TextStepWidget(
          step: step,
          initialValue: _currentText,
          onChanged: (val) => _currentText = val,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CustomerFlowProvider>();
    final step = provider.currentStep;
    final totalSteps = provider.steps.length;
    final currentIndex = provider.currentStepIndex;

    if (step == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Verification')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    final progress = totalSteps > 0 ? (currentIndex + 1) / totalSteps : 0.0;
    final isLastStep = currentIndex == totalSteps - 1;

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) async {
        if (didPop) return;
        if (currentIndex > 0) {
          _clearStepState();
          provider.previousStep();
        } else {
          final shouldLeave = await showDialog<bool>(
            context: context,
            builder: (ctx) => AlertDialog(
              title: const Text('Exit Verification?'),
              content: const Text(
                'Your progress so far has been recorded. You can return using the same link at any time.',
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Stay'),
                ),
                ElevatedButton(
                  onPressed: () => Navigator.pop(ctx, true),
                  child: const Text('Exit'),
                ),
              ],
            ),
          );
          if (shouldLeave == true && context.mounted) {
            context.go('/customer/${widget.token}');
          }
        }
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(provider.workflow?.workflowName ?? 'Evidence Submission'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Back',
            onPressed: () async {
              if (currentIndex > 0) {
                _clearStepState();
                provider.previousStep();
              } else {
                final shouldLeave = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text('Exit Verification?'),
                    content: const Text(
                      'Your progress so far has been recorded. You can return using the same link at any time.',
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(ctx, false),
                        child: const Text('Stay'),
                      ),
                      ElevatedButton(
                        onPressed: () => Navigator.pop(ctx, true),
                        child: const Text('Exit'),
                      ),
                    ],
                  ),
                );
                if (shouldLeave == true && context.mounted) {
                  context.go('/customer/${widget.token}');
                }
              }
            },
          ),
        ),
        body: SafeArea(
          child: Column(
            children: [
              // Linear Progress Indicator
              LinearProgressIndicator(
                value: progress,
                backgroundColor: AppColors.surfaceVariant,
                valueColor:
                    const AlwaysStoppedAnimation<Color>(AppColors.primary),
                minHeight: 4,
              ),

            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Step Counter & Title
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          'STEP ${currentIndex + 1} OF $totalSteps',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 0.6,
                            color: AppColors.primary,
                          ),
                        ),
                        if (step.required)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(
                              color: AppColors.surfaceVariant,
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: const Text(
                              'REQUIRED',
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.w600,
                                color: AppColors.textSecondary,
                              ),
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    if (provider.overview != null) ...[
                      Container(
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 6),
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight.withValues(alpha: 0.25),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.inventory_2_outlined,
                                size: 14, color: AppColors.primary),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                'Verifying item: ${provider.overview!.product.name}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.darkNeutral,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                    Text(
                      step.title,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                        color: AppColors.darkNeutral,
                        letterSpacing: -0.3,
                      ),
                    ),
                    const SizedBox(height: 20),

                    // Dynamic Step Form Widget
                    _buildStepWidget(step),
                    const SizedBox(height: 30),
                  ],
                ),
              ),
            ),

            // Navigation Bar
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              decoration: const BoxDecoration(
                color: Colors.white,
                border: Border(top: BorderSide(color: AppColors.border)),
              ),
              child: Row(
                children: [
                  if (currentIndex > 0) ...[
                    OutlinedButton(
                      onPressed: provider.isSubmitting
                          ? null
                          : () {
                              _clearStepState();
                              provider.previousStep();
                            },
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(80, 48),
                      ),
                      child: const Text('Back'),
                    ),
                    const SizedBox(width: 12),
                  ],
                  Expanded(
                    child: ElevatedButton(
                      onPressed: (provider.isSubmitting || _isSubmittingStep)
                          ? null
                          : () => _submitCurrentStep(provider, step),
                      child: (provider.isSubmitting || _isSubmittingStep)
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                valueColor:
                                    AlwaysStoppedAnimation<Color>(Colors.white),
                              ),
                            )
                          : Text(isLastStep ? 'Complete Submission' : 'Next Step'),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
}

import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../core/network/api_exception.dart';
import '../../models/evidence_models.dart';
import '../../state/customer_flow_provider.dart';

enum ProcessingStageStatus { waiting, processing, completed }

class ProcessingStage {
  final String id;
  final String label;
  ProcessingStageStatus status;

  ProcessingStage({
    required this.id,
    required this.label,
    this.status = ProcessingStageStatus.waiting,
  });
}

/// Dynamic interactive customer post-evidence processing screen reflecting
/// real backend verification stages and supporting adaptive follow-ups.
class ReviewingScreen extends StatefulWidget {
  final String token;

  const ReviewingScreen({super.key, required this.token});

  @override
  State<ReviewingScreen> createState() => _ReviewingScreenState();
}

class _ReviewingScreenState extends State<ReviewingScreen>
    with SingleTickerProviderStateMixin {
  final ImagePicker _picker = ImagePicker();
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  bool _analysisStarted = false;
  bool _needsFollowUp = false;
  CustomerEvidenceRequestModel? _activeRequest;
  String? _analysisError;

  // Dynamic stages built from workflow configuration
  List<ProcessingStage> _stages = [];

  // Follow-up answer state
  Uint8List? _followUpImageBytes;
  String? _followUpFilename;
  String? _selectedMcqOption;
  final TextEditingController _followUpTextController = TextEditingController();
  bool _isSubmittingFollowUp = false;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat(reverse: true);

    _pulseAnimation = Tween<double>(begin: 0.8, end: 1.25).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _runAnalysisPipeline();
    });
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _followUpTextController.dispose();
    super.dispose();
  }

  String _getSafeToken(CustomerFlowProvider provider) {
    final t = widget.token.trim();
    if (t.isNotEmpty) return t;
    final pt = provider.token?.trim();
    if (pt != null && pt.isNotEmpty) return pt;
    final ot = provider.overview?.verificationId.trim();
    if (ot != null && ot.isNotEmpty) return ot;
    return '';
  }

  void _initStages(CustomerFlowProvider provider) {
    if (_stages.isNotEmpty) return;
    final steps = provider.steps;
    final hasVisual =
        steps.any((s) => s.stepType == 'IMAGE' || s.stepType == 'CAMERA');
    final hasPayment = steps.any((s) => s.stepType == 'PAYMENT');
    final hasLocation = steps.any((s) => s.stepType == 'LOCATION');

    _stages = [
      ProcessingStage(
        id: 'check_evidence',
        label: 'Checking submitted evidence',
        status: ProcessingStageStatus.processing,
      ),
      if (hasVisual)
        ProcessingStage(
          id: 'visual_analysis',
          label: 'Analyzing visual evidence',
          status: ProcessingStageStatus.waiting,
        ),
      if (hasPayment)
        ProcessingStage(
          id: 'payment_signals',
          label: 'Verifying payment signals',
          status: ProcessingStageStatus.waiting,
        ),
      if (hasLocation)
        ProcessingStage(
          id: 'location_signals',
          label: 'Verifying location signals',
          status: ProcessingStageStatus.waiting,
        ),
      ProcessingStage(
        id: 'consistency',
        label: 'Reviewing evidence consistency',
        status: ProcessingStageStatus.waiting,
      ),
      ProcessingStage(
        id: 'submission',
        label: 'Preparing submission',
        status: ProcessingStageStatus.waiting,
      ),
    ];
  }

  void _setStageStatus(String id, ProcessingStageStatus status) {
    final index = _stages.indexWhere((s) => s.id == id);
    if (index != -1) {
      _stages[index].status = status;
    }
  }

  Future<void> _runAnalysisPipeline() async {
    if (_analysisStarted) return;
    final provider = context.read<CustomerFlowProvider>();

    setState(() {
      _analysisStarted = true;
      _analysisError = null;
      _initStages(provider);
      _setStageStatus('check_evidence', ProcessingStageStatus.processing);
    });

    try {
      // Stage 1: Checking submitted evidence (local + payload validation)
      await Future.delayed(const Duration(milliseconds: 400));
      if (!mounted) return;
      setState(() {
        _setStageStatus('check_evidence', ProcessingStageStatus.completed);
      });

      // Stage 2: Visual evidence analysis (real backend call)
      final hasVisualStage = _stages.any((s) => s.id == 'visual_analysis');
      if (hasVisualStage) {
        setState(() {
          _setStageStatus('visual_analysis', ProcessingStageStatus.processing);
        });

        final hasFollowUp = await provider.triggerLiveAnalysis();
        if (!mounted) return;

        if (hasFollowUp && provider.hasPendingAdaptiveRequests) {
          final req = provider.adaptiveRequests.firstWhere((r) => r.isPending);
          setState(() {
            _needsFollowUp = true;
            _activeRequest = req;
          });
          return;
        }

        setState(() {
          _setStageStatus('visual_analysis', ProcessingStageStatus.completed);
        });
      } else {
        // Even without visual images, trigger analysis to process signals
        final hasFollowUp = await provider.triggerLiveAnalysis();
        if (!mounted) return;
        if (hasFollowUp && provider.hasPendingAdaptiveRequests) {
          final req = provider.adaptiveRequests.firstWhere((r) => r.isPending);
          setState(() {
            _needsFollowUp = true;
            _activeRequest = req;
          });
          return;
        }
      }

      // Stage 3: Payment signals — processed by backend during triggerLiveAnalysis()
      // Mark complete immediately; no separate backend call required.
      if (_stages.any((s) => s.id == 'payment_signals')) {
        setState(() {
          _setStageStatus('payment_signals', ProcessingStageStatus.processing);
        });
        // Brief UI pause so user sees the stage transition (not a fake delay)
        await Future.delayed(const Duration(milliseconds: 180));
        if (!mounted) return;
        setState(() {
          _setStageStatus('payment_signals', ProcessingStageStatus.completed);
        });
      }

      // Stage 4: Location signals — also processed server-side with signal batch
      if (_stages.any((s) => s.id == 'location_signals')) {
        setState(() {
          _setStageStatus('location_signals', ProcessingStageStatus.processing);
        });
        await Future.delayed(const Duration(milliseconds: 180));
        if (!mounted) return;
        setState(() {
          _setStageStatus('location_signals', ProcessingStageStatus.completed);
        });
      }


      // Stage 5: Reviewing evidence consistency (fusion evaluation)
      setState(() {
        _setStageStatus('consistency', ProcessingStageStatus.processing);
      });
      await provider.loadFusionAssessment();
      if (!mounted) return;
      setState(() {
        _setStageStatus('consistency', ProcessingStageStatus.completed);
      });

      // Stage 6: Preparing submission (session finalization)
      setState(() {
        _setStageStatus('submission', ProcessingStageStatus.processing);
      });
      await provider.finalizeCompletion();
      if (!mounted) return;
      setState(() {
        _setStageStatus('submission', ProcessingStageStatus.completed);
      });

      // Brief transition delay so user sees full completion checkmark sequence
      await Future.delayed(const Duration(milliseconds: 500));
      if (!mounted) return;

      final safeToken = _getSafeToken(provider);
      if (safeToken.isNotEmpty) {
        context.go('/verify/$safeToken/completed');
      } else {
        context.go('/');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _analysisStarted = false;
        _analysisError = e is ApiException
            ? e.userMessage
            : 'Analysis could not be completed. Please try again.';
      });
    }
  }

  Future<void> _pickFollowUpImage() async {
    try {
      final photo = await _picker.pickImage(
        source: ImageSource.camera,
        imageQuality: 85,
        maxWidth: 1920,
        maxHeight: 1920,
      );
      if (photo != null) {
        final bytes = await photo.readAsBytes();
        setState(() {
          _followUpImageBytes = bytes;
          _followUpFilename = photo.name;
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open camera.')),
      );
    }
  }

  Future<void> _submitFollowUp() async {
    if (_isSubmittingFollowUp) return;
    final provider = context.read<CustomerFlowProvider>();
    if (_activeRequest == null) return;

    final type = _activeRequest!.requestedEvidenceType;

    if (type == 'MCQ') {
      if (_selectedMcqOption == null || _selectedMcqOption!.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please select an option.')),
        );
        return;
      }
    } else if (type == 'TEXT') {
      if (_followUpTextController.text.trim().isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please enter your response.')),
        );
        return;
      }
    } else {
      // Camera / Image follow-up
      if (_followUpImageBytes == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Please capture the requested photo proof.')),
        );
        return;
      }
    }

    setState(() {
      _isSubmittingFollowUp = true;
    });

    try {
      if (type == 'MCQ') {
        await provider.fulfillAdaptiveRequest(
          requestId: _activeRequest!.id,
          selectedOption: _selectedMcqOption!.trim(),
        );
      } else if (type == 'TEXT') {
        await provider.fulfillAdaptiveRequest(
          requestId: _activeRequest!.id,
          textContent: _followUpTextController.text.trim(),
        );
      } else {
        await provider.fulfillAdaptiveRequest(
          requestId: _activeRequest!.id,
          imageBytes: _followUpImageBytes!,
          filename: _followUpFilename ?? 'followup_.jpg',
        );
      }

      // Finalize session completion after follow-up
      await provider.finalizeCompletion();

      if (mounted) {
        final safeToken = _getSafeToken(provider);
        if (safeToken.isNotEmpty) {
          context.go('/verify/$safeToken/completed');
        } else {
          context.go('/');
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(provider.errorMessage ?? 'Submission failed. Please try again.'),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isSubmittingFollowUp = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CustomerFlowProvider>();

    return Scaffold(
      appBar: AppBar(
        title: Text(_needsFollowUp ? 'Follow-Up Verification' : 'Verifying Evidence'),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: _needsFollowUp
            ? _buildFollowUpScreen(context, provider)
            : _buildDynamicProcessingScreen(context),
      ),
    );
  }

  Widget _buildDynamicProcessingScreen(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 440),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // Animated Top Circle Icon
              Container(
                width: 80,
                height: 80,
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: AppColors.primaryLight.withValues(alpha: 0.35),
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.primary.withValues(alpha: 0.15),
                      blurRadius: 20,
                      spreadRadius: 6,
                    ),
                  ],
                ),
                child: _analysisError != null
                    ? const Icon(
                        Icons.error_outline_rounded,
                        size: 38,
                        color: AppColors.assessmentInconsistent,
                      )
                    : ScaleTransition(
                        scale: _pulseAnimation,
                        child: const Icon(
                          Icons.sync_rounded,
                          size: 36,
                          color: AppColors.primary,
                        ),
                      ),
              ),
              const SizedBox(height: 22),

              Text(
                _analysisError != null
                    ? 'Verification Issue'
                    : 'Verifying Evidence',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w800,
                  color: AppColors.darkNeutral,
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                _analysisError ??
                    'Please wait while your evidence is verified against workflow requirements.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 13,
                  color: _analysisError != null
                      ? AppColors.assessmentInconsistent
                      : AppColors.textSecondary,
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 28),

              // Interactive Stages Progress Card
              if (_analysisError == null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: AppColors.border),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.03),
                        blurRadius: 12,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                  child: Column(
                    children: _stages.map((stage) {
                      final isLast = stage == _stages.last;
                      return Padding(
                        padding: EdgeInsets.only(bottom: isLast ? 0 : 14),
                        child: Row(
                          children: [
                            // Status indicator (Pulse dot / Checkmark / Circle)
                            SizedBox(
                              width: 26,
                              height: 26,
                              child: Center(
                                child: stage.status ==
                                        ProcessingStageStatus.completed
                                    ? const Icon(
                                        Icons.check_circle_rounded,
                                        color: AppColors.assessmentConsistent,
                                        size: 22,
                                      )
                                    : stage.status ==
                                            ProcessingStageStatus.processing
                                        ? ScaleTransition(
                                            scale: _pulseAnimation,
                                            child: Container(
                                              width: 12,
                                              height: 12,
                                              decoration: BoxDecoration(
                                                color: AppColors.primary,
                                                shape: BoxShape.circle,
                                                boxShadow: [
                                                  BoxShadow(
                                                    color: AppColors.primary
                                                        .withValues(alpha: 0.45),
                                                    blurRadius: 6,
                                                    spreadRadius: 2,
                                                  ),
                                                ],
                                              ),
                                            ),
                                          )
                                        : Container(
                                            width: 12,
                                            height: 12,
                                            decoration: BoxDecoration(
                                              shape: BoxShape.circle,
                                              border: Border.all(
                                                color: AppColors.textMuted
                                                    .withValues(alpha: 0.6),
                                                width: 1.6,
                                              ),
                                            ),
                                          ),
                              ),
                            ),
                            const SizedBox(width: 12),

                            // Stage title
                            Expanded(
                              child: Text(
                                stage.label,
                                style: TextStyle(
                                  fontSize: 13.5,
                                  fontWeight: stage.status ==
                                          ProcessingStageStatus.processing
                                      ? FontWeight.w700
                                      : (stage.status ==
                                              ProcessingStageStatus.completed
                                          ? FontWeight.w600
                                          : FontWeight.w400),
                                  color: stage.status ==
                                          ProcessingStageStatus.waiting
                                      ? AppColors.textMuted
                                      : AppColors.darkNeutral,
                                ),
                              ),
                            ),

                            // Symbol icon representation (✓, ●, ○)
                            if (stage.status == ProcessingStageStatus.completed)
                              const Text(
                                '✓',
                                style: TextStyle(
                                  color: AppColors.assessmentConsistent,
                                  fontWeight: FontWeight.w800,
                                  fontSize: 15,
                                ),
                              )
                            else if (stage.status ==
                                ProcessingStageStatus.processing)
                              const Text(
                                '●',
                                style: TextStyle(
                                  color: AppColors.primary,
                                  fontWeight: FontWeight.w800,
                                  fontSize: 13,
                                ),
                              )
                            else
                              const Text(
                                '○',
                                style: TextStyle(
                                  color: AppColors.textMuted,
                                  fontWeight: FontWeight.w500,
                                  fontSize: 13,
                                ),
                              ),
                          ],
                        ),
                      );
                    }).toList(),
                  ),
                ),

              if (_analysisError != null) ...[
                const SizedBox(height: 20),
                ElevatedButton.icon(
                  onPressed: () {
                    setState(() {
                      _analysisStarted = false;
                      _stages.clear();
                    });
                    _runAnalysisPipeline();
                  },
                  icon: const Icon(Icons.refresh_rounded, size: 18),
                  label: const Text('Retry Verification'),
                  style: ElevatedButton.styleFrom(
                    minimumSize: const Size(200, 48),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFollowUpScreen(
      BuildContext context, CustomerFlowProvider provider) {
    final questionText = _activeRequest?.promptText ??
        _activeRequest?.reason ??
        'Please provide additional information for verification.';

    final type = _activeRequest?.requestedEvidenceType ?? 'CUSTOMER_IMAGE';
    final options = _activeRequest?.options ?? [];

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 500),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // ─── Submission progress indicator ───────────────────────────
            if (_isSubmittingFollowUp) ...[
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: AppColors.primaryLight.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppColors.primary.withValues(alpha: 0.3)),
                ),
                child: const Row(
                  children: [
                    SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: 12),
                    Text(
                      'Submitting response and running analysis…',
                      style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: AppColors.darkNeutral,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              const LinearProgressIndicator(),
              const SizedBox(height: 14),
            ],

            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppColors.assessmentReviewRequiredBg,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color:
                      AppColors.assessmentReviewRequired.withValues(alpha: 0.5),
                ),
              ),
              child: const Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.help_outline_rounded,
                    color: AppColors.assessmentReviewRequired,
                    size: 24,
                  ),
                  SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Additional Information Needed',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        SizedBox(height: 4),
                        Text(
                          'Please answer the question below to help complete verification of your claim.',
                          style: TextStyle(
                            fontSize: 12.5,
                            color: AppColors.textSecondary,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),

            // Question Card
            Card(
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
                side: const BorderSide(color: AppColors.border),
              ),
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'VERIFICATION QUESTION',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.6,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      questionText,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: AppColors.darkNeutral,
                        height: 1.4,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 18),

            // Render type-specific follow-up input
            if (type == 'MCQ' && options.isNotEmpty) ...[
              ...options.map((opt) {
                final isSelected = _selectedMcqOption == opt;
                return Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  decoration: BoxDecoration(
                    color: isSelected
                        ? AppColors.primaryLight.withValues(alpha: 0.3)
                        : Colors.white,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: isSelected ? AppColors.primary : AppColors.border,
                      width: isSelected ? 1.5 : 1.0,
                    ),
                  ),
                  child: InkWell(
                    onTap: () => setState(() => _selectedMcqOption = opt),
                    borderRadius: BorderRadius.circular(10),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 12),
                      child: Row(
                        children: [
                          Icon(
                            isSelected
                                ? Icons.radio_button_checked_rounded
                                : Icons.radio_button_off_rounded,
                            color: isSelected
                                ? AppColors.primary
                                : AppColors.textMuted,
                            size: 20,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              opt,
                              style: TextStyle(
                                fontSize: 13.5,
                                fontWeight: isSelected
                                    ? FontWeight.w600
                                    : FontWeight.w400,
                                color: AppColors.darkNeutral,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }),
            ] else if (type == 'TEXT') ...[
              TextField(
                controller: _followUpTextController,
                maxLines: 4,
                decoration: InputDecoration(
                  hintText: 'Describe details here...',
                  hintStyle: const TextStyle(fontSize: 13),
                  contentPadding: const EdgeInsets.all(14),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ] else ...[
              // Camera / Image follow-up
              if (_followUpImageBytes == null) ...[
                Container(
                  padding: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    color: AppColors.surfaceVariant.withValues(alpha: 0.4),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: AppColors.primary.withValues(alpha: 0.3),
                      width: 1.5,
                    ),
                  ),
                  child: Column(
                    children: [
                      const Icon(
                        Icons.camera_alt_rounded,
                        size: 36,
                        color: AppColors.primary,
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Camera required',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'Capture a live camera photo addressing the question above.',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 12,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 18),
                      ElevatedButton.icon(
                        onPressed: _pickFollowUpImage,
                        icon: const Icon(Icons.camera_alt_rounded, size: 20),
                        label: const Text('Capture Proof'),
                        style: ElevatedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 48),
                        ),
                      ),
                    ],
                  ),
                ),
              ] else ...[
                Container(
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppColors.primary),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: Image.memory(
                    _followUpImageBytes!,
                    height: 220,
                    width: double.infinity,
                    fit: BoxFit.contain,
                    cacheHeight: 440,
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.check_circle_rounded,
                            color: AppColors.assessmentConsistent, size: 16),
                        SizedBox(width: 6),
                        Text(
                          'Follow-up photo ready',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ],
                    ),
                    TextButton.icon(
                      onPressed: _pickFollowUpImage,
                      icon: const Icon(Icons.refresh_rounded, size: 16),
                      label: const Text('Retake Photo'),
                    ),
                  ],
                ),
              ],
            ],
            const SizedBox(height: 20),

            ElevatedButton(
              onPressed: provider.isSubmitting ? null : _submitFollowUp,
              style: ElevatedButton.styleFrom(
                minimumSize: const Size(double.infinity, 48),
              ),
              child: provider.isSubmitting
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    )
                  : const Text('Submit Response'),
            ),
          ],
        ),
      ),
    );
  }
}

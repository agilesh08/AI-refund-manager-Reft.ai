import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../shared/widgets/assessment_badge.dart';
import '../../shared/widgets/decision_badge.dart';
import '../../shared/widgets/section_card.dart';
import '../../shared/widgets/status_badge.dart';
import '../../state/merchant_dashboard_provider.dart';
import 'decision_dialog.dart';

/// 9-Section Explainable Final Verification Report Screen.
class ReportScreen extends StatefulWidget {
  final String verificationId;

  const ReportScreen({super.key, required this.verificationId});

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  void _openDecisionDialog(MerchantDashboardProvider provider, {String? initialDecision}) {
    showDialog(
      context: context,
      builder: (ctx) => DecisionDialog(
        verificationId: widget.verificationId,
        initialDecision: initialDecision,
        onConfirm: (decision) async {
          final ok = await provider.submitDecision(
            widget.verificationId,
            decision,
          );
          if (ok && mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Merchant decision recorded.')),
            );
          }
        },
      ),
    );
  }

  void _handleHold(MerchantDashboardProvider provider) {
    int? selectedDuration = 86400;
    final reasonCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (dialogCtx) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
              title: const Row(
                children: [
                  Icon(Icons.pause_circle_filled_rounded, color: AppColors.statusHeld, size: 22),
                  SizedBox(width: 8),
                  Text('Hold Verification', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                ],
              ),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Select duration to pause customer access to this verification:',
                      style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        _buildDurationChip('1 hour', 3600, selectedDuration, (val) => setDialogState(() => selectedDuration = val)),
                        _buildDurationChip('6 hours', 21600, selectedDuration, (val) => setDialogState(() => selectedDuration = val)),
                        _buildDurationChip('24 hours', 86400, selectedDuration, (val) => setDialogState(() => selectedDuration = val)),
                        _buildDurationChip('3 days', 259200, selectedDuration, (val) => setDialogState(() => selectedDuration = val)),
                        _buildDurationChip('Indefinite', null, selectedDuration, (val) => setDialogState(() => selectedDuration = val)),
                      ],
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: reasonCtrl,
                      decoration: InputDecoration(
                        labelText: 'Hold Reason (Optional)',
                        hintText: 'e.g. Waiting for inspection',
                        hintStyle: const TextStyle(fontSize: 11.5),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                      ),
                      style: const TextStyle(fontSize: 12.5),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogCtx),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.statusHeld,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  ),
                  onPressed: () async {
                    Navigator.pop(dialogCtx);
                    final reason = reasonCtrl.text.trim().isEmpty ? null : reasonCtrl.text.trim();
                    final success = await provider.holdVerification(
                      widget.verificationId,
                      durationSeconds: selectedDuration,
                      reason: reason,
                    );
                    if (context.mounted && success) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Verification session placed on hold.')),
                      );
                    }
                  },
                  child: const Text('Hold Session'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Widget _buildDurationChip(String label, int? seconds, int? currentSelection, Function(int?) onSelect) {
    final isSelected = currentSelection == seconds;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => onSelect(seconds),
      selectedColor: AppColors.statusHeldBg,
      labelStyle: TextStyle(
        fontSize: 11,
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        color: isSelected ? AppColors.statusHeld : AppColors.darkNeutral,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(8),
        side: BorderSide(
          color: isSelected ? AppColors.statusHeld : AppColors.border,
        ),
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context
          .read<MerchantDashboardProvider>()
          .loadReport(widget.verificationId);
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<MerchantDashboardProvider>();
    final report = provider.selectedReport;

    if (provider.isLoadingDetail || report == null) {
      return Scaffold(
        appBar: AppBar(
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Back',
            onPressed: () {
              if (context.canPop()) {
                context.pop();
              } else {
                context.go('/investigation/${widget.verificationId}');
              }
            },
          ),
          title: const Text('Explainable Final Report'),
        ),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: 'Back to Investigation',
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go('/investigation/${widget.verificationId}');
            }
          },
        ),
        title: const Text('Verification Report'),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Assessment Header Card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'FINAL VERIFICATION REPORT',
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 0.6,
                                color: AppColors.textSecondary,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Session #${report.verificationId}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 14.5,
                                fontWeight: FontWeight.w800,
                                color: AppColors.darkNeutral,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      AssessmentBadge(
                        assessmentState: report.assessmentState,
                        confidence: report.overallConfidence,
                        compact: true,
                      ),
                    ],
                  ),
                  if (report.recommendationLabel != null && report.recommendationLabel!.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      decoration: BoxDecoration(
                        color: AppColors.primaryLight.withValues(alpha: 0.35),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppColors.primary.withValues(alpha: 0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.recommend_rounded, color: AppColors.primary, size: 20),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Recommendation: ${report.recommendationLabel}',
                                  style: const TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w800,
                                    color: AppColors.primary,
                                  ),
                                ),
                                const SizedBox(height: 1),
                                const Text(
                                  'Deterministic recommendation only. Sole authoritative decision is made by the merchant.',
                                  style: TextStyle(fontSize: 10.5, color: AppColors.textSecondary),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),

            // Section 1: Executive Summary & Identity
            SectionCard(
              title: 'Executive Summary & Claim',
              icon: Icons.article_outlined,
              child: _buildExecutiveSummary(report.executiveSummary),
            ),

            // Section 2: Consistency Assessment Output
            SectionCard(
              title: 'Consistency Assessment',
              icon: Icons.fact_check_outlined,
              child: _buildConsistencyAssessment(report.consistencyAssessment),
            ),

            // Section 3: Visual Consistency Findings (Gemini Vision)
            SectionCard(
              title: 'Visual Evidence Findings',
              icon: Icons.image_search_outlined,
              child: _buildVisualFindings(report.visualConsistencyFindings),
            ),

            // Section 4: Deterministic Multi-Source Signals
            SectionCard(
              title: 'Deterministic Transaction Signals',
              icon: Icons.payments_outlined,
              child: _buildSignalFindings(report.signalVerificationFindings),
            ),

            // Section 5: Multi-Source Fusion Matrix
            SectionCard(
              title: 'Multi-Source Fusion Matrix',
              icon: Icons.hub_outlined,
              child: _buildFusionMatrix(report.multiSourceFusionMatrix),
            ),

            // Section 6: Claim vs Evidence Reconciliation
            SectionCard(
              title: 'Claim vs Evidence Reconciliation',
              icon: Icons.compare_arrows_rounded,
              child: _buildClaimVsEvidence(report.claimVsEvidenceReconciliation),
            ),

            // Section 7: Missing Evidence and Follow-Up Record
            SectionCard(
              title: 'Missing Evidence & Adaptive Follow-Up',
              icon: Icons.help_outline_rounded,
              child: _buildMissingEvidence(report.missingEvidenceAndFollowUp),
            ),

            // Section 8: Merchant Decision Context
            SectionCard(
              title: 'Merchant Human Decision Context',
              icon: Icons.gavel_rounded,
              child: _buildDecisionContext(report.merchantDecisionContext),
            ),

            // Section 9: AI Audit Trail & Synthesized Explainability
            SectionCard(
              title: 'Audit Trail & Verification Engine',
              icon: Icons.psychology_outlined,
              child: _buildAiAuditTrail(report.aiAuditTrail),
            ),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.white,
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.06),
                blurRadius: 10,
                offset: const Offset(0, -3),
              ),
            ],
            border: const Border(top: BorderSide(color: AppColors.border, width: 0.8)),
          ),
          child: Row(
            children: [
              Expanded(
                flex: 3,
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    side: const BorderSide(color: AppColors.statusHeld),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: () => _handleHold(provider),
                  icon: const Icon(Icons.pause_circle_outline_rounded, size: 16, color: AppColors.statusHeld),
                  label: const Text('HOLD', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.statusHeld)),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 4,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    backgroundColor: Colors.red.shade700,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: () => _openDecisionDialog(provider, initialDecision: 'REFUND_REJECTED'),
                  icon: const Icon(Icons.close_rounded, size: 16),
                  label: const Text('REJECT', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                flex: 4,
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    backgroundColor: const Color(0xFF059669),
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: () => _openDecisionDialog(provider, initialDecision: 'REFUND_APPROVED'),
                  icon: const Icon(Icons.check_rounded, size: 16),
                  label: const Text('APPROVE', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Section 1: Executive Summary
  // ---------------------------------------------------------------------------
  Widget _buildExecutiveSummary(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('Executive summary pending.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final text = data['text']?.toString() ?? 'Assessment complete.';
    final confidence = (data['overall_confidence'] as num?)?.toDouble() ?? 0.0;
    final state = data['assessment_state']?.toString() ?? 'REVIEW_REQUIRED';
    final reviewRecommended = data['review_recommended'] == true;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.surfaceVariant,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            text,
            style: const TextStyle(
              fontSize: 13,
              color: AppColors.darkNeutral,
              height: 1.4,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _buildMetricItem(
              'Confidence Score',
              '${(confidence * 100).toInt()}%',
              icon: Icons.speed_rounded,
              color: AppColors.primary,
            ),
            _buildMetricItem(
              'Review Advised',
              reviewRecommended ? 'Yes' : 'No',
              icon: reviewRecommended
                  ? Icons.warning_amber_rounded
                  : Icons.check_circle_outline_rounded,
              color: reviewRecommended
                  ? AppColors.assessmentReviewRequired
                  : AppColors.assessmentConsistent,
            ),
            _buildMetricItem(
              'Assessment State',
              state.replaceAll('_', ' '),
              icon: Icons.insights_rounded,
              color: AppColors.forAssessment(state),
            ),
          ],
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 2: Consistency Assessment
  // ---------------------------------------------------------------------------
  Widget _buildConsistencyAssessment(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('Consistency assessment pending.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final state = data['state']?.toString() ?? 'REVIEW_REQUIRED';
    final confidence = (data['confidence'] as num?)?.toDouble();
    final reasoning = data['reasoning']?.toString() ?? 'No reasoning provided.';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            AssessmentBadge(
              assessmentState: state,
              confidence: confidence,
            ),
          ],
        ),
        const SizedBox(height: 10),
        const Text(
          'Automated Reasoning Summary:',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w700,
            color: AppColors.textSecondary,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          reasoning,
          style: const TextStyle(fontSize: 13, height: 1.35),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 3: Visual Findings
  // ---------------------------------------------------------------------------
  Widget _buildVisualFindings(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('No visual analysis items recorded.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final totalImages = data['total_images'] ?? 0;
    final refsComplete = data['references_complete'] == true;
    final refAngles = data['trusted_reference_angles_available'] ?? 0;
    final items = data['items'] as List? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _buildChip(
              'Images Analyzed: $totalImages',
              Icons.camera_alt_outlined,
              AppColors.primary,
            ),
            const SizedBox(width: 8),
            _buildChip(
              refsComplete ? '4 Reference Angles (Complete)' : '$refAngles Reference Angles',
              Icons.verified_outlined,
              refsComplete ? AppColors.assessmentConsistent : AppColors.textSecondary,
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (items.isEmpty)
          const Text(
            'No item-level visual observations yet.',
            style: TextStyle(fontSize: 12, color: AppColors.textMuted),
          )
        else
          ...items.map((it) {
            if (it is! Map) return const SizedBox.shrink();
            final evId = it['evidence_id']?.toString() ?? 'Item';
            final status = it['status']?.toString() ?? 'PENDING';
            final consistency = it['product_consistency']?.toString();
            final condition = it['visible_condition']?.toString();
            final observations = it['key_visual_observations'] as List? ?? [];
            final uncertainties = it['uncertainties'] as List? ?? [];

            return Container(
              margin: const EdgeInsets.only(bottom: 10),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: AppColors.surfaceVariant.withValues(alpha: 0.5),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Evidence #$evId',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      StatusBadge(status: status),
                    ],
                  ),
                  if (consistency != null) ...[
                    const SizedBox(height: 6),
                    _buildRow('Catalog Consistency', consistency),
                  ],
                  if (condition != null) ...[
                    const SizedBox(height: 4),
                    _buildRow('Visible Condition', condition),
                  ],
                  if (observations.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    const Text(
                      'Observations:',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    ...observations.map((o) => Padding(
                          padding: const EdgeInsets.only(left: 6, top: 2),
                          child: Text(
                            '• ${o.toString()}',
                            style: const TextStyle(fontSize: 12),
                          ),
                        )),
                  ],
                  if (uncertainties.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    ...uncertainties.map((u) => Padding(
                          padding: const EdgeInsets.only(left: 6, top: 2),
                          child: Text(
                            '⚠ ${u.toString()}',
                            style: const TextStyle(
                              fontSize: 11,
                              color: AppColors.assessmentReviewRequired,
                            ),
                          ),
                        )),
                  ],
                ],
              ),
            );
          }),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 4: Signal Findings
  // ---------------------------------------------------------------------------
  Widget _buildSignalFindings(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('No deterministic signals recorded.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final paymentStatus = data['payment_signal_status']?.toString() ?? 'NO_SIGNAL';
    final orderStatus = data['order_signal_status']?.toString() ?? 'NO_SIGNAL';
    final deliveryStatus = data['delivery_signal_status']?.toString() ?? 'NO_SIGNAL';
    final locationStatus = data['location_signal_status']?.toString() ?? 'NO_SIGNAL';
    final signals = data['signals'] as List? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            _buildSignalStatusBadge('Payment', paymentStatus),
            _buildSignalStatusBadge('Order', orderStatus),
            _buildSignalStatusBadge('Delivery', deliveryStatus),
            _buildSignalStatusBadge('Location', locationStatus),
          ],
        ),
        if (signals.isNotEmpty) ...[
          const SizedBox(height: 12),
          ...signals.map((sig) {
            if (sig is! Map) return const SizedBox.shrink();
            final type = sig['signal_type']?.toString() ?? 'SIGNAL';
            final source = sig['source_type']?.toString() ?? 'SYSTEM';
            final status = sig['status']?.toString() ?? 'VALID';

            return Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  const Icon(Icons.check_circle_outline,
                      size: 14, color: AppColors.assessmentConsistent),
                  const SizedBox(width: 6),
                  Text(
                    '$type ($source)',
                    style: const TextStyle(
                        fontSize: 12, fontWeight: FontWeight.w600),
                  ),
                  const Spacer(),
                  StatusBadge(status: status),
                ],
              ),
            );
          }),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 5: Fusion Matrix
  // ---------------------------------------------------------------------------
  Widget _buildFusionMatrix(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('Fusion matrix data unavailable.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final dimensions = data['dimensions'] as List? ?? [];
    final contradictions = data['contradictions'] as List? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (dimensions.isEmpty)
          const Text('No dimensions evaluated.',
              style: TextStyle(color: AppColors.textMuted))
        else
          ...dimensions.map((d) {
            if (d is! Map) return const SizedBox.shrink();
            final dim = d['dimension']?.toString().replaceAll('_', ' ') ?? 'DIMENSION';
            final status = d['status']?.toString() ?? 'INSUFFICIENT';
            final conf = (d['confidence'] as num?)?.toDouble() ?? 0.0;
            final explanation = d['explanation']?.toString();

            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: AppColors.surfaceVariant.withValues(alpha: 0.4),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Text(
                          dim,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ),
                      _buildDimensionBadge(status, conf),
                    ],
                  ),
                  if (explanation != null && explanation.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      explanation,
                      style: const TextStyle(
                          fontSize: 11, color: AppColors.textSecondary),
                    ),
                  ],
                ],
              ),
            );
          }),
        if (contradictions.isNotEmpty) ...[
          const SizedBox(height: 8),
          const Text(
            'Contradictions Detected:',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.assessmentInconsistent,
            ),
          ),
          const SizedBox(height: 4),
          ...contradictions.map((c) {
            final desc = c is Map
                ? (c['description'] ??
                        c['reason'] ??
                        c['explanation'] ??
                        c['summary'] ??
                        c['conflict_type'] ??
                        'Discrepancy detected')
                    .toString()
                : c.toString();
            return Padding(
              padding: const EdgeInsets.only(left: 6, bottom: 4),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.error_outline,
                      size: 14, color: AppColors.assessmentInconsistent),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(desc, style: const TextStyle(fontSize: 12)),
                  ),
                ],
              ),
            );
          }),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 6: Claim vs Evidence Reconciliation
  // ---------------------------------------------------------------------------
  Widget _buildClaimVsEvidence(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('Reconciliation data unavailable.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final alignment = data['alignment']?.toString() ?? 'PARTIALLY_ALIGNED';
    final claimed = data['customer_claimed'] as Map? ?? {};
    final evidence = data['evidence_shows'] as Map? ?? {};

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text(
              'Evidence Alignment: ',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
            ),
            _buildAlignmentBadge(alignment),
          ],
        ),
        const SizedBox(height: 10),
        _buildRow(
            'Claimed Reason', claimed['refund_reason']?.toString() ?? 'N/A'),
        if (claimed['claimed_condition'] != null)
          _buildRow('Claimed Condition', claimed['claimed_condition'].toString()),
        if (claimed['refund_amount'] != null)
          _buildRow('Requested Refund', '₹${claimed['refund_amount']}'),
        const Divider(height: 16),
        _buildRow(
            'Visual Evidence', evidence['visual_summary']?.toString() ?? 'N/A'),
        _buildRow(
            'Signal Verification', evidence['signal_summary']?.toString() ?? 'N/A'),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 7: Missing Evidence
  // ---------------------------------------------------------------------------
  Widget _buildMissingEvidence(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('No missing evidence or follow-up recorded.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final totalMissing = data['total_missing'] ?? 0;
    final adaptive = data['adaptive_requests'] as List? ?? [];
    final missingList = data['missing_evidence'] as List? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _buildChip(
              totalMissing == 0 ? 'No Missing Evidence' : '$totalMissing Missing Items',
              totalMissing == 0 ? Icons.check_circle_outline : Icons.warning_amber_rounded,
              totalMissing == 0 ? AppColors.assessmentConsistent : AppColors.assessmentReviewRequired,
            ),
          ],
        ),
        if (missingList.isNotEmpty) ...[
          const SizedBox(height: 8),
          ...missingList.map((m) {
            final desc = m is Map
                ? (m['description'] ??
                        m['reason'] ??
                        m['explanation'] ??
                        m['summary'] ??
                        m['step_key'] ??
                        'Missing evidence item')
                    .toString()
                : m.toString();
            return Padding(
              padding: const EdgeInsets.only(left: 6, bottom: 2),
              child: Text('• $desc', style: const TextStyle(fontSize: 12)),
            );
          }),
        ],
        if (adaptive.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text(
            'Follow-Up Requests Issued:',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 6),
          ...adaptive.map((r) {
            if (r is! Map) return const SizedBox.shrink();
            final key = r['step_key']?.toString() ?? 'Request';
            final status = r['status']?.toString() ?? 'PENDING';
            final reason = r['reason']?.toString();

            return Container(
              margin: const EdgeInsets.only(bottom: 6),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: AppColors.surfaceVariant,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          key,
                          style: const TextStyle(
                              fontSize: 12, fontWeight: FontWeight.w600),
                        ),
                        if (reason != null)
                          Text(
                            reason,
                            style: const TextStyle(
                                fontSize: 11, color: AppColors.textSecondary),
                          ),
                      ],
                    ),
                  ),
                  StatusBadge(status: status),
                ],
              ),
            );
          }),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 8: Merchant Decision Context
  // ---------------------------------------------------------------------------
  Widget _buildDecisionContext(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('Merchant decision context unavailable.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final latest = data['latest_decision'] as Map?;
    final policies = data['policy_recommendations'] as List? ?? [];
    final actions = data['available_actions'] as List? ?? [];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (latest != null) ...[
          Row(
            children: [
              const Text('Recorded Decision: ',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
              DecisionBadge(decision: latest['decision']?.toString()),
            ],
          ),
          if (latest['decision_reason'] != null || latest['notes'] != null) ...[
            const SizedBox(height: 6),
            Text(
              'Notes: ${latest['decision_reason'] ?? latest['notes']}',
              style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
            ),
          ],
          const Divider(height: 16),
        ] else ...[
          const Row(
            children: [
              Icon(Icons.pending_actions_rounded,
                  size: 16, color: AppColors.textMuted),
              SizedBox(width: 6),
              Text(
                'No decision recorded yet. Merchant review pending.',
                style: TextStyle(fontSize: 12, color: AppColors.textSecondary),
              ),
            ],
          ),
          const SizedBox(height: 10),
        ],
        if (policies.isNotEmpty) ...[
          const Text(
            'Policy Framework:',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppColors.textSecondary,
            ),
          ),
          const SizedBox(height: 4),
          ...policies.map((p) => Padding(
                padding: const EdgeInsets.only(left: 6, bottom: 2),
                child: Text('• ${p.toString()}',
                    style: const TextStyle(fontSize: 11)),
              )),
        ],
        if (actions.isNotEmpty) ...[
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            children: actions.map((a) {
              return Chip(
                label: Text(
                  a.toString().replaceAll('_', ' '),
                  style: const TextStyle(fontSize: 10),
                ),
                visualDensity: VisualDensity.compact,
              );
            }).toList(),
          ),
        ],
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Section 9: AI Audit Trail & Synthesized Reasoning
  // ---------------------------------------------------------------------------
  Widget _buildAiAuditTrail(Map<String, dynamic> data) {
    if (data.isEmpty) {
      return const Text('AI audit trail not recorded.',
          style: TextStyle(color: AppColors.textMuted));
    }
    final status = data['status']?.toString() ?? 'COMPLETED';
    final explanation = data['explanation'];

    String summaryText = 'Automated synthesis completed.';
    if (explanation is Map) {
      summaryText = explanation['summary']?.toString() ??
          explanation['claim_assessment']?.toString() ??
          summaryText;
    } else if (explanation != null) {
      summaryText = explanation.toString();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            _buildChip(
              'Verification Reasoning',
              Icons.memory_rounded,
              AppColors.primary,
            ),
            const SizedBox(width: 8),
            _buildChip(
              'Automated Synthesis',
              Icons.smart_toy_outlined,
              AppColors.textSecondary,
            ),
            const Spacer(),
            StatusBadge(status: status),
          ],
        ),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.surfaceVariant.withValues(alpha: 0.6),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppColors.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Row(
                children: [
                  Icon(Icons.lightbulb_outline_rounded,
                      size: 15, color: AppColors.primary),
                  SizedBox(width: 6),
                  Text(
                    'Synthesized Explanation',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.primary,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                summaryText,
                style: const TextStyle(fontSize: 12, height: 1.4),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // ---------------------------------------------------------------------------
  // Helper Widgets
  // ---------------------------------------------------------------------------
  Widget _buildRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 140,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: AppColors.darkNeutral,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMetricItem(String title, String value,
      {required IconData icon, required Color color}) {
    return Column(
      children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(height: 4),
        Text(
          value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: color,
          ),
        ),
        Text(
          title,
          style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
        ),
      ],
    );
  }

  Widget _buildChip(String label, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSignalStatusBadge(String signalName, String status) {
    Color color;
    IconData icon;
    String label;

    switch (status.toUpperCase()) {
      case 'MATCHED':
        color = AppColors.assessmentConsistent;
        icon = Icons.check_circle_rounded;
        label = 'Matched';
        break;
      case 'UNMATCHED':
        color = AppColors.assessmentInconsistent;
        icon = Icons.cancel_rounded;
        label = 'Mismatch';
        break;
      default:
        color = AppColors.textMuted;
        icon = Icons.remove_circle_outline_rounded;
        label = 'Not Ingested';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 4),
          Text(
            '$signalName: $label',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDimensionBadge(String status, double confidence) {
    Color color;
    switch (status.toUpperCase()) {
      case 'CONSISTENT':
        color = AppColors.assessmentConsistent;
        break;
      case 'INCONSISTENT':
        color = AppColors.assessmentInconsistent;
        break;
      default:
        color = AppColors.assessmentReviewRequired;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        '${status.replaceAll('_', ' ')} (${(confidence * 100).toInt()}%)',
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }

  Widget _buildAlignmentBadge(String alignment) {
    Color color;
    String label;
    switch (alignment.toUpperCase()) {
      case 'ALIGNED':
        color = AppColors.assessmentConsistent;
        label = 'Aligned';
        break;
      case 'CONTRADICTORY':
        color = AppColors.assessmentInconsistent;
        label = 'Contradictory';
        break;
      default:
        color = AppColors.assessmentReviewRequired;
        label = 'Partially Aligned';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(5),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

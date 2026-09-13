import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../models/report_models.dart';
import '../../shared/widgets/assessment_badge.dart';
import '../../shared/widgets/decision_badge.dart';
import '../../shared/widgets/section_card.dart';
import '../../shared/widgets/status_badge.dart';
import '../../state/merchant_dashboard_provider.dart';
import 'decision_dialog.dart';

/// Comprehensive Merchant Investigation View with Full Evidence Trail & Decision Bar.
class InvestigationScreen extends StatefulWidget {
  final String verificationId;

  const InvestigationScreen({super.key, required this.verificationId});

  @override
  State<InvestigationScreen> createState() => _InvestigationScreenState();
}

class _InvestigationScreenState extends State<InvestigationScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context
          .read<MerchantDashboardProvider>()
          .loadInvestigationDetail(widget.verificationId);
    });
  }

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

  void _handleHoldOrResume(
      MerchantDashboardProvider provider, VerificationDetailDashboardModel detail) async {
    if (detail.isHeld) {
      final ok = await provider.resumeVerification(detail.verificationId);
      if (ok && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Verification session resumed.')),
        );
      }
    } else {
      _showHoldDurationDialog(context, provider, detail);
    }
  }

  void _showHoldDurationDialog(
      BuildContext context,
      MerchantDashboardProvider provider,
      VerificationDetailDashboardModel detail) {
    int? selectedDuration = 86400; // 24 hours default
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
                        hintText: 'e.g. Waiting for physical return',
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
                      detail.verificationId,
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

  String _formatTimeRemaining(DateTime until) {
    final diff = until.difference(DateTime.now());
    if (diff.isNegative) return 'shortly';
    if (diff.inHours >= 24) {
      final days = diff.inDays;
      final hours = diff.inHours % 24;
      return 'in ${days}d ${hours}h';
    }
    if (diff.inHours > 0) {
      return 'in ${diff.inHours}h ${diff.inMinutes % 60}m';
    }
    return 'in ${diff.inMinutes}m';
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<MerchantDashboardProvider>();
    final detail = provider.selectedVerification;

    if (provider.isLoadingDetail || detail == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Investigation View')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    final dateFormat = DateFormat('MMM d, yyyy • HH:mm');
    final createdAtStr = detail.verification['created_at'] != null
        ? dateFormat.format(
            DateTime.tryParse(detail.verification['created_at'].toString()) ??
                DateTime.now())
        : 'N/A';

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
        title: const Text('Verification Investigation'),
        actions: [
          TextButton.icon(
            onPressed: () => context.push('/investigation/${widget.verificationId}/customer-response'),
            icon: const Icon(Icons.assignment_ind_outlined, color: Colors.white, size: 18),
            label: const Text(
              'Customer Response',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 80),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Top Verification Status & Recommendation Card
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: AppColors.border, width: 0.9),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.02),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Order #${detail.orderId}',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                      StatusBadge(status: detail.status),
                    ],
                  ),
                  if (detail.isHeld) ...[
                    const SizedBox(height: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: AppColors.statusHeldBg,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppColors.statusHeld.withValues(alpha: 0.3)),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.pause_circle_filled_rounded, size: 15, color: AppColors.statusHeld),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              detail.holdUntil != null
                                  ? 'Paused by merchant • Resumes ${_formatTimeRemaining(detail.holdUntil!)}'
                                  : 'Paused by merchant (indefinite hold)',
                              style: const TextStyle(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w600,
                                color: AppColors.statusHeld,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      AssessmentBadge(
                        assessmentState: detail.assessmentState,
                        confidence: detail.fusionResult?.overallConfidence,
                      ),
                      if (detail.merchantDecision != null)
                        DecisionBadge(decision: detail.merchantDecision!.decision),
                    ],
                  ),
                  if (detail.recommendationLabel != null && detail.recommendationLabel!.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    _buildAiAnalysisBanner(detail.recommendationLabel!),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 14),

            // Prominent Customer Response Entry Button
            // Prominent Customer Response Entry Button Action Card
            InkWell(
              onTap: () {
                context.push('/investigation/${widget.verificationId}/customer-response');
              },
              borderRadius: BorderRadius.circular(12),
              child: Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      AppColors.primary.withValues(alpha: 0.08),
                      AppColors.primaryLight.withValues(alpha: 0.15),
                    ],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.primary.withValues(alpha: 0.25)),
                ),
                padding: const EdgeInsets.all(14),
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final isCompact = constraints.maxWidth < 360;
                    if (isCompact) {
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          const Row(
                            children: [
                              Icon(Icons.person_pin_rounded, color: AppColors.primary, size: 22),
                              SizedBox(width: 8),
                              Text(
                                'Customer Response Dossier',
                                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.darkNeutral),
                              ),
                            ],
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'Review customer claims, answers, evidence & audit trail',
                            style: TextStyle(fontSize: 11.5, color: AppColors.textSecondary),
                          ),
                          const SizedBox(height: 10),
                          ElevatedButton.icon(
                            onPressed: () {
                              context.push('/investigation/${widget.verificationId}/customer-response');
                            },
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.primary,
                              foregroundColor: Colors.white,
                              minimumSize: const Size(double.infinity, 38),
                            ),
                            icon: const Icon(Icons.person_search_outlined, size: 16),
                            label: const Text('Open Customer Response'),
                          ),
                        ],
                      );
                    }
                    return Row(
                      children: [
                        Container(
                          width: 42,
                          height: 42,
                          decoration: BoxDecoration(
                            color: AppColors.primary.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(
                            Icons.person_pin_rounded,
                            color: AppColors.primary,
                            size: 22,
                          ),
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Customer Response Dossier',
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.darkNeutral,
                                ),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'Review customer claims, answers, evidence & audit trail',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: AppColors.textSecondary,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton.icon(
                          onPressed: () {
                            context.push('/investigation/${widget.verificationId}/customer-response');
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppColors.primary,
                            foregroundColor: Colors.white,
                            elevation: 0,
                            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(8),
                            ),
                          ),
                          icon: const Icon(Icons.person_search_outlined, size: 16),
                          label: const Text(
                            'Open Customer Response',
                            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ),

            const SizedBox(height: 14),

            // 1. Customer Claim Details
            SectionCard(
              title: 'Customer Claim Details',
              icon: Icons.record_voice_over_outlined,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (detail.claim['customer_name'] != null)
                    _buildKeyValue('Customer Name', detail.claim['customer_name'].toString()),
                  if (detail.claim['customer_contact'] != null)
                    _buildKeyValue('Contact / Phone', detail.claim['customer_contact'].toString()),
                  if (detail.verification['customer_email'] != null)
                    _buildKeyValue('Email', detail.verification['customer_email'].toString()),
                  _buildKeyValue('Claim Reason', detail.claim['refund_reason'] ?? 'Not specified'),
                  if (detail.claim['refund_amount'] != null)
                    _buildKeyValue('Refund Amount', '₹${detail.claim['refund_amount']}'),
                  if (detail.claim['claimed_item_condition'] != null)
                    _buildKeyValue('Reported Condition', detail.claim['claimed_item_condition'].toString()),
                  _buildKeyValue('Created At', createdAtStr),
                ],
              ),
            ),

            // 2. Claimed Product Information
            SectionCard(
              title: 'Claimed Product Details',
              icon: Icons.inventory_2_outlined,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildKeyValue('Product Name', detail.product['name'] ?? 'N/A'),
                  if (detail.product['sku'] != null)
                    _buildKeyValue('SKU', detail.product['sku'].toString()),
                  if (detail.product['price'] != null)
                    _buildKeyValue('Catalog Price', '₹${detail.product['price']}'),
                  if (detail.product['reference_count'] != null)
                    _buildKeyValue('Reference Angles', '${detail.product['reference_count']} verified images registered'),
                ],
              ),
            ),

            // 3. Questions Asked & Customer Answers
            SectionCard(
              title: 'Questions Asked & Customer Answers',
              icon: Icons.quiz_outlined,
              child: detail.questionsAsked.isEmpty
                  ? const Text(
                      'No specific workflow questions registered.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.textMuted),
                    )
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: detail.questionsAsked.map((q) {
                        final title = q['title'] ?? q['step_key'] ?? 'Question';
                        final answer = q['answer'] ?? (q['submitted'] == true ? 'Evidence submitted' : 'Pending submission');
                        final req = q['required'] == true;
                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceVariant.withValues(alpha: 0.5),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: AppColors.border),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      title.toString(),
                                      style: const TextStyle(
                                        fontSize: 12.5,
                                        fontWeight: FontWeight.w700,
                                        color: AppColors.darkNeutral,
                                      ),
                                    ),
                                  ),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: req ? AppColors.primaryLight.withValues(alpha: 0.5) : Colors.grey.shade200,
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(
                                      req ? 'Required' : 'Optional',
                                      style: TextStyle(
                                        fontSize: 10,
                                        fontWeight: FontWeight.w600,
                                        color: req ? AppColors.primary : AppColors.textSecondary,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Answer: $answer',
                                style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                              ),
                            ],
                          ),
                        );
                      }).toList(),
                    ),
            ),

            // 4. Adaptive Follow-Up Questions & Responses
            SectionCard(
              title: 'Adaptive Follow-Up Questions',
              icon: Icons.dynamic_feed_rounded,
              child: detail.adaptiveFollowUpQuestions.isEmpty
                  ? const Text(
                      'No adaptive follow-up questions were required.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.textMuted),
                    )
                  : Column(
                      children: detail.adaptiveFollowUpQuestions.map((req) {
                        final prompt = req['prompt'] ?? req['reason'] ?? 'Follow-up request';
                        final status = req['status'] ?? 'PENDING';
                        final response = req['customer_response'] ?? 'Awaiting response';
                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceVariant.withValues(alpha: 0.5),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: AppColors.border),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      prompt.toString(),
                                      style: const TextStyle(
                                        fontSize: 12.5,
                                        fontWeight: FontWeight.w700,
                                        color: AppColors.darkNeutral,
                                      ),
                                    ),
                                  ),
                                  StatusBadge(status: status.toString()),
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                'Response: $response',
                                style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                              ),
                            ],
                          ),
                        );
                      }).toList(),
                    ),
            ),

            // 5. Customer Evidence Gallery
            SectionCard(
              title: 'Uploaded Evidence Gallery (${detail.evidenceItems.length})',
              icon: Icons.photo_library_outlined,
              child: detail.evidenceItems.isEmpty
                  ? const Text(
                      'No evidence submitted yet.',
                      style: TextStyle(fontSize: 12.5, color: AppColors.textMuted),
                    )
                  : Column(
                      children: detail.evidenceItems.map((ev) {
                        final createdStr = ev.createdAt != null
                            ? DateFormat('MMM d, HH:mm').format(ev.createdAt!)
                            : 'Recent';
                        final hashPrefix = (ev.sha256Hash != null && ev.sha256Hash!.length >= 8)
                            ? ev.sha256Hash!.substring(0, 8)
                            : null;
                        return Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceVariant.withValues(alpha: 0.5),
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: AppColors.border),
                          ),
                          child: Row(
                            children: [
                              Icon(
                                ev.evidenceType.contains('IMAGE')
                                    ? Icons.image_outlined
                                    : Icons.article_outlined,
                                color: AppColors.primary,
                                size: 22,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      ev.workflowStepKey ?? ev.evidenceType,
                                      style: const TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    if (ev.originalFilename != null)
                                      Text(
                                        ev.originalFilename!,
                                        style: const TextStyle(fontSize: 11.5, color: AppColors.darkNeutral),
                                      ),
                                    if (ev.textContent != null)
                                      Text(
                                        ev.textContent!,
                                        maxLines: 2,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(fontSize: 11.5, color: AppColors.textSecondary),
                                      ),
                                    Text(
                                      'Submitted $createdStr${hashPrefix != null ? ' • SHA: $hashPrefix...' : ''}',
                                      style: const TextStyle(fontSize: 10.5, color: AppColors.textMuted),
                                    ),
                                  ],
                                ),
                              ),
                              StatusBadge(status: ev.isDuplicate ? 'DUPLICATE' : 'UPLOADED'),
                            ],
                          ),
                        );
                      }).toList(),
                    ),
            ),

            // 6. Visual Inspection Findings (Categorized: Observed, Not Observed, Unclear)
            SectionCard(
              title: 'Visual Inspection Findings',
              icon: Icons.visibility_outlined,
              child: _buildCategorizedVisualFindings(detail),
            ),

            // 7. Concise Deterministic Signal Statuses
            SectionCard(
              title: 'Concise Deterministic Signals',
              icon: Icons.sync_alt_rounded,
              child: _buildDeterministicSignalsSection(detail),
            ),

            // 8. Plain-Language Verification Reasoning
            SectionCard(
              title: 'Verification Reasoning & Synthesis',
              icon: Icons.lightbulb_outline_rounded,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.surfaceVariant.withValues(alpha: 0.6),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      detail.llamaReasoning?['summary'] ??
                          detail.fusionResult?.explanation['summary'] ??
                          'Evidence assessment synthesized from submitted photos, claim attributes, and verified merchant signals.',
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.darkNeutral,
                        height: 1.4,
                      ),
                    ),
                  ),
                  if (detail.fusionResult != null && detail.fusionResult!.contradictions.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    const Text(
                      'Discrepancies Observed:',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.assessmentInconsistent,
                      ),
                    ),
                    const SizedBox(height: 4),
                    ...detail.fusionResult!.contradictions.map((c) {
                      String text = '';
                      if (c is Map) {
                        text = (c['description'] ??
                                c['reason'] ??
                                c['conflict_type'] ??
                                'Discrepancy detected')
                            .toString();
                      } else {
                        text = c.toString();
                      }
                      return Padding(
                        padding: const EdgeInsets.only(left: 6, bottom: 3),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('• ', style: TextStyle(color: AppColors.assessmentInconsistent)),
                            Expanded(child: Text(text, style: const TextStyle(fontSize: 12))),
                          ],
                        ),
                      );
                    }),
                  ],
                ],
              ),
            ),

            // 9. Chronological Audit Trail Preview
            SectionCard(
              title: 'Audit Trail & Chronology',
              icon: Icons.history_rounded,
              trailing: TextButton(
                onPressed: () => context.push('/timeline/${widget.verificationId}'),
                child: const Text('Full Timeline'),
              ),
              child: Text(
                '${detail.timeline.length} immutable audit events recorded for this session.',
                style: const TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
              ),
            ),

            // 10. Authoritative Merchant Decision History
            if (detail.merchantDecision != null) ...[
              SectionCard(
                title: 'Recorded Merchant Decision',
                icon: Icons.gavel_rounded,
                accentColor: AppColors.primary,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Current Decision:',
                          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                        ),
                        DecisionBadge(decision: detail.merchantDecision!.decision),
                      ],
                    ),
                    if (detail.merchantDecision!.notes != null &&
                        detail.merchantDecision!.notes!.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        'Notes: ${detail.merchantDecision!.notes}',
                        style: const TextStyle(
                          fontSize: 12,
                          fontStyle: FontStyle.italic,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
      // Sticky 3-way decision bar: [ HOLD / RESUME ], [ REJECT ], [ APPROVE ]
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
              // [ HOLD / RESUME ]
              Expanded(
                flex: 3,
                child: OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    side: BorderSide(
                      color: detail.isHeld ? AppColors.primary : AppColors.statusHeld,
                    ),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: () => _handleHoldOrResume(provider, detail),
                  icon: Icon(
                    detail.isHeld ? Icons.play_arrow_rounded : Icons.pause_circle_outline_rounded,
                    size: 16,
                    color: detail.isHeld ? AppColors.primary : AppColors.statusHeld,
                  ),
                  label: Text(
                    detail.isHeld ? 'RESUME' : 'HOLD',
                    style: TextStyle(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w700,
                      color: detail.isHeld ? AppColors.primary : AppColors.statusHeld,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // [ REJECT ]
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
                  label: const Text(
                    'REJECT',
                    style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // [ APPROVE ]
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
                  label: const Text(
                    'APPROVE',
                    style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCategorizedVisualFindings(VerificationDetailDashboardModel detail) {
    final cat = detail.visualFindingsCategorized;
    final observed = (cat['observed'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [];
    final notObserved = (cat['not_observed'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [];
    final unclear = (cat['unclear'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [];

    if (observed.isEmpty && notObserved.isEmpty && unclear.isEmpty) {
      if (detail.visualAnalysisItems.isEmpty) {
        return const Text(
          'Visual inspection pending or no photos submitted.',
          style: TextStyle(fontSize: 12.5, color: AppColors.textMuted),
        );
      }
      return const Text(
        'Visual observations processed.',
        style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (observed.isNotEmpty) ...[
          const Row(
            children: [
              Icon(Icons.check_circle_outline_rounded, size: 15, color: Color(0xFF059669)),
              SizedBox(width: 6),
              Text(
                'Observed',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFF059669)),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ...observed.map((o) => Padding(
                padding: const EdgeInsets.only(left: 20, bottom: 4),
                child: Text('• $o', style: const TextStyle(fontSize: 12, color: AppColors.darkNeutral)),
              )),
          const SizedBox(height: 8),
        ],
        if (notObserved.isNotEmpty) ...[
          const Row(
            children: [
              Icon(Icons.cancel_outlined, size: 15, color: Colors.red),
              SizedBox(width: 6),
              Text(
                'Not Observed',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Colors.red),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ...notObserved.map((n) => Padding(
                padding: const EdgeInsets.only(left: 20, bottom: 4),
                child: Text('• $n', style: const TextStyle(fontSize: 12, color: AppColors.darkNeutral)),
              )),
          const SizedBox(height: 8),
        ],
        if (unclear.isNotEmpty) ...[
          const Row(
            children: [
              Icon(Icons.help_outline_rounded, size: 15, color: Color(0xFFD97706)),
              SizedBox(width: 6),
              Text(
                'Unclear / Ambiguous',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: Color(0xFFD97706)),
              ),
            ],
          ),
          const SizedBox(height: 4),
          ...unclear.map((u) => Padding(
                padding: const EdgeInsets.only(left: 20, bottom: 4),
                child: Text('• $u', style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
              )),
        ],
      ],
    );
  }

  Widget _buildDeterministicSignalsSection(VerificationDetailDashboardModel detail) {
    final sigMap = detail.deterministicSignalStatuses;
    final signals = [
      {'key': 'PAYMENT', 'label': 'Payment', 'icon': Icons.payment_rounded},
      {'key': 'ORDER', 'label': 'Order', 'icon': Icons.shopping_bag_outlined},
      {'key': 'DELIVERY', 'label': 'Delivery', 'icon': Icons.local_shipping_outlined},
      {'key': 'LOCATION', 'label': 'Location', 'icon': Icons.location_on_outlined},
    ];

    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: signals.map((s) {
        final key = s['key'] as String;
        final label = s['label'] as String;
        final icon = s['icon'] as IconData;
        final status = sigMap[key] ?? 'Unavailable';

        Color stColor = Colors.grey;
        Color stBg = Colors.grey.shade100;
        if (status.toLowerCase().contains('verified') || status.toLowerCase().contains('matched')) {
          stColor = const Color(0xFF059669);
          stBg = const Color(0xFFECFDF5);
        } else if (status.toLowerCase().contains('mismatch') || status.toLowerCase().contains('invalid')) {
          stColor = Colors.red;
          stBg = const Color(0xFFFEF2F2);
        }

        return Container(
          width: 150,
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: stBg,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: stColor.withValues(alpha: 0.3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(icon, size: 14, color: stColor),
                  const SizedBox(width: 5),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: stColor,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 2),
              Text(
                status,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  color: stColor,
                ),
              ),
            ],
          ),
        );
      }).toList(),
    );
  }

  Widget _buildKeyValue(String key, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 140,
            child: Text(
              key,
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.darkNeutral,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAiAnalysisBanner(String label) {
    final norm = label.toUpperCase();

    // 5-band verdict system matching backend map_confidence_to_recommendation()
    Color bannerColor;
    Color bannerBg;
    IconData icon;
    FontWeight labelWeight;

    if (norm.startsWith('REJECT') && !norm.contains('CAN REJECT')) {
      // REJECT — Evidence Insufficient  (< 35%)
      bannerColor = const Color(0xFFDC2626); // Crimson Red
      bannerBg = const Color(0xFFFEF2F2);
      icon = Icons.cancel_rounded;
      labelWeight = FontWeight.w900;
    } else if (norm.contains('CAN REJECT') || norm.contains('CAN_REJECT')) {
      // CAN REJECT — Significant Discrepancies  (35–50%)
      bannerColor = const Color(0xFFEA580C); // Deep Orange
      bannerBg = const Color(0xFFFFF7ED);
      icon = Icons.remove_circle_outline_rounded;
      labelWeight = FontWeight.w800;
    } else if (norm.contains('MOSTLY APPROVE') || norm.contains('MOSTLY_APPROVE')) {
      // MOSTLY APPROVE — Evidence Supports Claim  (75–85%)
      bannerColor = const Color(0xFF0D9488); // Teal
      bannerBg = const Color(0xFFF0FDFA);
      icon = Icons.check_circle_outline_rounded;
      labelWeight = FontWeight.w800;
    } else if (norm.contains('APPROVED') && !norm.contains('MOSTLY')) {
      // APPROVED — Strong Evidence  (≥ 85%)
      bannerColor = const Color(0xFF059669); // Emerald Green
      bannerBg = const Color(0xFFECFDF5);
      icon = Icons.check_circle_rounded;
      labelWeight = FontWeight.w900;
    } else {
      // REVIEW REQUIRED — Mixed Evidence  (50–75%) or unknown
      bannerColor = const Color(0xFFD97706); // Amber
      bannerBg = const Color(0xFFFFFBEB);
      icon = Icons.warning_amber_rounded;
      labelWeight = FontWeight.w800;
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: bannerBg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: bannerColor.withValues(alpha: 0.4), width: 1.2),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Icon(icon, color: bannerColor, size: 28),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'AI ANALYSIS',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 0.8,
                    color: bannerColor.withValues(alpha: 0.85),
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: labelWeight,
                    color: bannerColor,
                    letterSpacing: 0.2,
                  ),
                ),
                const SizedBox(height: 2),
                const Text(
                  'Merchant maintains sole authority to decide.',
                  style: TextStyle(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w500,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}


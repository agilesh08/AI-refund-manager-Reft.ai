import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../models/report_models.dart';
import '../../shared/widgets/assessment_badge.dart';
import '../../shared/widgets/decision_badge.dart';
import '../../shared/widgets/stat_card.dart';
import '../../shared/widgets/status_badge.dart';
import '../../state/auth_provider.dart';
import '../../state/merchant_dashboard_provider.dart';

/// Merchant Dashboard screen with summary stats, multi-criteria filters, and paginated verifications list.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<MerchantDashboardProvider>().loadVerifications();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  DateTime? _lastResumeTime;

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && mounted) {
      final now = DateTime.now();
      if (_lastResumeTime == null ||
          now.difference(_lastResumeTime!).inMilliseconds > 2000) {
        _lastResumeTime = now;
        context.read<MerchantDashboardProvider>().loadVerifications(refresh: true);
      }
    }
  }

  void _showFilterBottomSheet(
      BuildContext context, MerchantDashboardProvider provider) {
    String tempStatus = provider.statusFilter;
    String tempAssessment = provider.assessmentFilter;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Handle bar
                    Center(
                      child: Container(
                        width: 36,
                        height: 4,
                        decoration: BoxDecoration(
                          color: Colors.grey.shade300,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ),
                    const SizedBox(height: 14),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Filter Verifications',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w800,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        TextButton(
                          onPressed: () {
                            setModalState(() {
                              tempStatus = 'ALL';
                              tempAssessment = 'ALL';
                            });
                          },
                          child: const Text('Reset All',
                              style: TextStyle(fontSize: 12)),
                        ),
                      ],
                    ),
                    const Divider(height: 16),
                    const SizedBox(height: 4),

                    // Section 1: Session Status
                    const Text(
                      'STATUS',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.5,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        _buildModalFilterChip('All', tempStatus == 'ALL', () {
                          setModalState(() => tempStatus = 'ALL');
                        }),
                        _buildModalFilterChip('Created', tempStatus == 'CREATED', () {
                          setModalState(() => tempStatus = 'CREATED');
                        }),
                        _buildModalFilterChip('In Progress', tempStatus == 'IN_PROGRESS', () {
                          setModalState(() => tempStatus = 'IN_PROGRESS');
                        }),
                        _buildModalFilterChip('Completed', tempStatus == 'COMPLETED', () {
                          setModalState(() => tempStatus = 'COMPLETED');
                        }),
                        _buildModalFilterChip('Expired', tempStatus == 'EXPIRED', () {
                          setModalState(() => tempStatus = 'EXPIRED');
                        }),
                        _buildModalFilterChip('Cancelled', tempStatus == 'CANCELLED', () {
                          setModalState(() => tempStatus = 'CANCELLED');
                        }),
                        _buildModalFilterChip('On Hold', tempStatus == 'HELD', () {
                          setModalState(() => tempStatus = 'HELD');
                        }),
                      ],
                    ),
                    const SizedBox(height: 18),

                    // Section 2: AI Assessment
                    const Text(
                      'ASSESSMENT',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.5,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 6,
                      children: [
                        _buildModalFilterChip('All', tempAssessment == 'ALL', () {
                          setModalState(() => tempAssessment = 'ALL');
                        }),
                        _buildModalFilterChip(
                            'Consistent', tempAssessment == 'EVIDENCE_CONSISTENT', () {
                          setModalState(() => tempAssessment = 'EVIDENCE_CONSISTENT');
                        }),
                        _buildModalFilterChip('Review Required', tempAssessment == 'REVIEW_REQUIRED', () {
                          setModalState(() => tempAssessment = 'REVIEW_REQUIRED');
                        }),
                        _buildModalFilterChip(
                            'Inconsistent', tempAssessment == 'INCONSISTENCY_DETECTED', () {
                          setModalState(() => tempAssessment = 'INCONSISTENCY_DETECTED');
                        }),
                      ],
                    ),
                    const SizedBox(height: 22),

                    // Reset and Apply Action Buttons
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                            onPressed: () {
                              setModalState(() {
                                tempStatus = 'ALL';
                                tempAssessment = 'ALL';
                              });
                              provider.setStatusFilter('ALL');
                              provider.setAssessmentFilter('ALL');
                              Navigator.pop(ctx);
                            },
                            child: const Text('Reset'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            style: ElevatedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                            onPressed: () {
                              provider.setStatusFilter(tempStatus);
                              provider.setAssessmentFilter(tempAssessment);
                              Navigator.pop(ctx);
                            },
                            child: const Text('Apply Filters'),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildModalFilterChip(
      String label, bool isSelected, VoidCallback onSelected) {
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (_) => onSelected(),
      selectedColor: AppColors.primaryLight,
      checkmarkColor: AppColors.primary,
      labelStyle: TextStyle(
        fontSize: 12,
        fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
        color: isSelected ? AppColors.primary : AppColors.darkNeutral,
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

  void _showSessionActionMenu(BuildContext context, DashboardVerificationItemModel item) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 36,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 12),
                  decoration: BoxDecoration(
                    color: Colors.grey.shade300,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                  child: Row(
                    children: [
                      const Icon(Icons.tune_rounded, size: 18, color: AppColors.primary),
                      const SizedBox(width: 8),
                      Text(
                        'Session: ${item.orderId}',
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w700,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                    ],
                  ),
                ),
                const Divider(height: 16),
                if (item.isHeld)
                  ListTile(
                    leading: const Icon(Icons.play_arrow_rounded, color: AppColors.primary),
                    title: const Text('Resume verification', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                    subtitle: const Text('Re-enable customer access to verification flow', style: TextStyle(fontSize: 11)),
                    onTap: () async {
                      Navigator.pop(ctx);
                      final success = await context.read<MerchantDashboardProvider>().resumeVerification(item.verificationId);
                      if (context.mounted && success) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('Verification session resumed')),
                        );
                      }
                    },
                  )
                else
                  ListTile(
                    leading: const Icon(Icons.pause_circle_outline_rounded, color: AppColors.statusHeld),
                    title: const Text('Hold this session', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13.5)),
                    subtitle: const Text('Temporarily pause customer evidence link', style: TextStyle(fontSize: 11)),
                    onTap: () {
                      Navigator.pop(ctx);
                      _showHoldDurationDialog(context, item);
                    },
                  ),
                ListTile(
                  leading: const Icon(Icons.delete_outline_rounded, color: Colors.red),
                  title: const Text('Delete this session', style: TextStyle(color: Colors.red, fontWeight: FontWeight.w600, fontSize: 13.5)),
                  subtitle: const Text('Permanently remove session and uploaded files', style: TextStyle(fontSize: 11)),
                  onTap: () {
                    Navigator.pop(ctx);
                    _showDeleteConfirmationDialog(context, item);
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  void _showHoldDurationDialog(BuildContext context, DashboardVerificationItemModel item) {
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
                        hintText: 'e.g. Waiting for physical inspection',
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
                    final success = await context.read<MerchantDashboardProvider>().holdVerification(
                      item.verificationId,
                      durationSeconds: selectedDuration,
                      reason: reason,
                    );
                    if (context.mounted && success) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Verification session placed on hold')),
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

  void _showDeleteConfirmationDialog(BuildContext context, DashboardVerificationItemModel item) {
    showDialog(
      context: context,
      builder: (dialogCtx) {
        return AlertDialog(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Row(
            children: [
              Icon(Icons.warning_amber_rounded, color: Colors.red, size: 22),
              SizedBox(width: 8),
              Text('Delete verification?', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            ],
          ),
          content: const Text(
            'This will permanently remove the verification session, customer evidence, and audit logs. This cannot be undone.',
            style: TextStyle(fontSize: 12.5, color: AppColors.textSecondary),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogCtx),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.red,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
              ),
              onPressed: () async {
                Navigator.pop(dialogCtx);
                final success = await context.read<MerchantDashboardProvider>().deleteVerification(item.verificationId);
                if (context.mounted && success) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Verification session deleted')),
                  );
                }
              },
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );
  }

  Widget _buildVerificationCard(
      BuildContext context, DashboardVerificationItemModel item) {
    final formattedDate = DateFormat('MMM d, yyyy • HH:mm').format(item.createdAt);

    return Container(
      margin: const EdgeInsets.only(bottom: 11),
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
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () async {
            await context.push('/investigation/${item.verificationId}');
            if (context.mounted) {
              context.read<MerchantDashboardProvider>().loadVerifications(refresh: true);
            }
          },
          onLongPress: () => _showSessionActionMenu(context, item),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Top row: Order ID & Status & Action Menu
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Row(
                        children: [
                          const Icon(Icons.receipt_long_rounded,
                              size: 15, color: AppColors.primary),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              item.orderId,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 13.5,
                                fontWeight: FontWeight.w700,
                                color: AppColors.darkNeutral,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        StatusBadge(status: item.status),
                        const SizedBox(width: 4),
                        InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: () => _showSessionActionMenu(context, item),
                          child: const Padding(
                            padding: EdgeInsets.all(2.0),
                            child: Icon(Icons.more_vert_rounded,
                                size: 16, color: AppColors.textSecondary),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                if (item.isHeld) ...[
                  const SizedBox(height: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppColors.statusHeldBg,
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                        color: AppColors.statusHeld.withValues(alpha: 0.3),
                      ),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.pause_circle_filled_rounded,
                            size: 13, color: AppColors.statusHeld),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            item.holdUntil != null
                                ? 'Paused by merchant • Resumes ${_formatTimeRemaining(item.holdUntil!)}'
                                : 'Paused by merchant (indefinite)',
                            style: const TextStyle(
                              fontSize: 10.5,
                              fontWeight: FontWeight.w600,
                              color: AppColors.statusHeld,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 7),

                // Product name & amount
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        item.productName ?? 'Product',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 13.5,
                          fontWeight: FontWeight.w600,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    if (item.refundAmount != null)
                      Text(
                        '₹${item.refundAmount!.toStringAsFixed(2)}',
                        style: const TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w800,
                          color: AppColors.primary,
                        ),
                      ),
                  ],
                ),
                if (item.refundReason != null &&
                    item.refundReason!.trim().isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Claim: ',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      Expanded(
                        child: Text(
                          item.refundReason!.trim(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 11.5,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 8),

                // Assessment Header & Badges row
                const Text(
                  'Verification Assessment',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.3,
                    color: AppColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 5,
                  children: [
                    AssessmentBadge(
                      assessmentState: item.assessmentState,
                      confidence: item.confidence,
                      compact: true,
                    ),
                    DecisionBadge(
                      decision: item.isHeld
                          ? 'HOLD'
                          : (item.latestDecision ?? 'AWAITING DECISION'),
                      compact: true,
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                const Divider(height: 1),
                const SizedBox(height: 8),

                // Bottom footer: Evidence count & Date
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Expanded(
                      child: Text(
                        '${item.evidenceCount} evidence • $formattedDate',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ),
                    const Icon(
                      Icons.chevron_right_rounded,
                      size: 18,
                      color: AppColors.textSecondary,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<MerchantDashboardProvider>();

    return Scaffold(
      appBar: AppBar(
        title: Image.asset(
          'assets/branding/reft_wordmark.png',
          width: 118,
          fit: BoxFit.contain,
          semanticLabel: 'Reft.AI',
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'Settings',
            onPressed: () => context.push('/settings'),
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: () => provider.loadVerifications(refresh: true),
          ),
          IconButton(
            icon: const Icon(Icons.logout_rounded),
            tooltip: 'Sign Out',
            onPressed: () async {
              await context.read<AuthProvider>().logout();
              if (context.mounted) context.go('/');
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => provider.loadVerifications(refresh: true),
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Context Area
                    const Text(
                      'Verification Overview',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                        color: AppColors.darkNeutral,
                        letterSpacing: -0.3,
                      ),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Review customer refund claims and visual AI evidence analysis',
                      style: TextStyle(
                        fontSize: 12,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 14),

                    // Summary Stats Grid (2 Cards: TOTAL and REVIEW REQUIRED)
                    Row(
                      children: [
                        Expanded(
                          child: StatCard(
                            title: 'Total',
                            value: '${provider.totalCount}',
                            subtitle: 'Verifications',
                            icon: Icons.assignment_outlined,
                            color: AppColors.primary,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: StatCard(
                            title: 'Review Required',
                            value: '${provider.reviewRequiredCount}',
                            subtitle: 'Need attention',
                            icon: Icons.warning_amber_rounded,
                            color: AppColors.assessmentReviewRequired,
                            backgroundColor:
                                AppColors.assessmentReviewRequiredBg,
                            onTap: () => provider
                                .setAssessmentFilter('REVIEW_REQUIRED'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),

                    // Primary Create Action Card
                    Container(
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [AppColors.primary, Color(0xFF4A6B8A)],
                          begin: Alignment.topLeft,
                          end: Alignment.bottomRight,
                        ),
                        borderRadius: BorderRadius.circular(14),
                        boxShadow: [
                          BoxShadow(
                            color: AppColors.primary.withValues(alpha: 0.22),
                            blurRadius: 10,
                            offset: const Offset(0, 3),
                          ),
                        ],
                      ),
                      child: Material(
                        color: Colors.transparent,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(14),
                          onTap: () async {
                            await context.push('/create-verification');
                            if (context.mounted) {
                              context
                                  .read<MerchantDashboardProvider>()
                                  .loadVerifications(refresh: true);
                            }
                          },
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 16, vertical: 14),
                            child: Row(
                              children: [
                                Container(
                                  padding: const EdgeInsets.all(8),
                                  decoration: const BoxDecoration(
                                    color: Colors.white24,
                                    shape: BoxShape.circle,
                                  ),
                                  child: const Icon(Icons.add_rounded,
                                      color: Colors.white, size: 20),
                                ),
                                const SizedBox(width: 14),
                                const Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'Create New Verification',
                                        style: TextStyle(
                                          color: Colors.white,
                                          fontSize: 15,
                                          fontWeight: FontWeight.w700,
                                        ),
                                      ),
                                      SizedBox(height: 2),
                                      Text(
                                        'Create a secure evidence verification for a customer refund claim.',
                                        style: TextStyle(
                                          color: Colors.white70,
                                          fontSize: 11.5,
                                          height: 1.3,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const Icon(Icons.arrow_forward_ios_rounded,
                                    color: Colors.white70, size: 14),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Filter & Queue Header Row
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Verification Queue',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w800,
                                color: AppColors.darkNeutral,
                                letterSpacing: -0.2,
                              ),
                            ),
                            SizedBox(height: 2),
                            Text(
                              'Customer claims requiring review',
                              style: TextStyle(
                                fontSize: 11.5,
                                color: AppColors.textSecondary,
                              ),
                            ),
                          ],
                        ),
                        OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 12, vertical: 8),
                            minimumSize: const Size(0, 36),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                            side: BorderSide(
                              color: (provider.statusFilter != 'ALL' ||
                                      provider.assessmentFilter != 'ALL')
                                  ? AppColors.primary
                                  : AppColors.border,
                            ),
                            backgroundColor: (provider.statusFilter != 'ALL' ||
                                    provider.assessmentFilter != 'ALL')
                                ? AppColors.primaryLight.withValues(alpha: 0.25)
                                : Colors.white,
                          ),
                          icon: Icon(
                            Icons.filter_list_rounded,
                            size: 15,
                            color: (provider.statusFilter != 'ALL' ||
                                    provider.assessmentFilter != 'ALL')
                                ? AppColors.primary
                                : AppColors.textSecondary,
                          ),
                          label: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                (provider.statusFilter != 'ALL' ||
                                        provider.assessmentFilter != 'ALL')
                                    ? 'Filter • ${((provider.statusFilter != 'ALL' ? 1 : 0) + (provider.assessmentFilter != 'ALL' ? 1 : 0))}'
                                    : 'Filter',
                                style: TextStyle(
                                  fontSize: 12.5,
                                  fontWeight: FontWeight.w700,
                                  color: (provider.statusFilter != 'ALL' ||
                                          provider.assessmentFilter != 'ALL')
                                      ? AppColors.primary
                                      : AppColors.darkNeutral,
                                ),
                              ),
                              const SizedBox(width: 2),
                              const Icon(Icons.arrow_drop_down_rounded, size: 16),
                            ],
                          ),
                          onPressed: () =>
                              _showFilterBottomSheet(context, provider),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                  ],
                ),
              ),
            ),

            // List of Sessions
            if (provider.isLoadingList)
              const SliverFillRemaining(
                hasScrollBody: false,
                child: Center(child: CircularProgressIndicator()),
              )
            else if (provider.errorMessage != null && provider.items.isEmpty)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.error_outline_rounded,
                            size: 48, color: AppColors.assessmentInconsistent),
                        const SizedBox(height: 12),
                        Text(
                          provider.errorMessage!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton.icon(
                          onPressed: () =>
                              provider.loadVerifications(refresh: true),
                          icon: const Icon(Icons.refresh_rounded, size: 18),
                          label: const Text('Retry'),
                        ),
                      ],
                    ),
                  ),
                ),
              )
            else if (provider.items.isEmpty)
              SliverFillRemaining(
                hasScrollBody: false,
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.inbox_outlined,
                          size: 48, color: AppColors.textMuted),
                      const SizedBox(height: 12),
                      const Text(
                        'No verification sessions found',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      TextButton(
                        onPressed: () {
                          provider.setSearch('');
                          provider.setStatusFilter('ALL');
                          provider.setAssessmentFilter('ALL');
                        },
                        child: const Text('Reset filters'),
                      ),
                    ],
                  ),
                ),
              )
            else
              SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                sliver: SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      final item = provider.items[index];
                      return _buildVerificationCard(context, item);
                    },
                    childCount: provider.items.length,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

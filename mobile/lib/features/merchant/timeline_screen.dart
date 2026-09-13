import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../state/merchant_dashboard_provider.dart';

/// Vertical chronological timeline screen of immutable verification audit events.
class TimelineScreen extends StatefulWidget {
  final String verificationId;

  const TimelineScreen({super.key, required this.verificationId});

  @override
  State<TimelineScreen> createState() => _TimelineScreenState();
}

class _TimelineScreenState extends State<TimelineScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context
          .read<MerchantDashboardProvider>()
          .loadTimeline(widget.verificationId);
    });
  }

  Color _colorForSource(String source) {
    switch (source.toUpperCase()) {
      case 'MERCHANT':
        return AppColors.decisionApproved;
      case 'CUSTOMER':
        return AppColors.statusInProgress;
      case 'VISUAL AI':
      case 'GEMINI_VISION':
        return Colors.purple;
      case 'VERIFICATION REASONING':
      case 'LLAMA_REASONING':
        return Colors.teal;
      case 'EXTERNAL_SIGNAL':
        return Colors.indigo;
      case 'SYSTEM':
      default:
        return AppColors.textSecondary;
    }
  }

  String _labelForSource(String source) {
    switch (source.toUpperCase()) {
      case 'GEMINI_VISION':
        return 'VISUAL AI';
      case 'LLAMA_REASONING':
        return 'VERIFICATION REASONING';
      default:
        return source.replaceAll('_', ' ');
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<MerchantDashboardProvider>();
    final timeline = provider.selectedTimeline;

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
        title: const Text('Audit Event Timeline'),
      ),
      body: provider.isLoadingDetail
          ? const Center(child: CircularProgressIndicator())
          : timeline.isEmpty
              ? const Center(
                  child: Text(
                    'No timeline events found for this session.',
                    style: TextStyle(color: AppColors.textMuted),
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(20),
                  itemCount: timeline.length,
                  itemBuilder: (context, index) {
                    final item = timeline[index];
                    final isLast = index == timeline.length - 1;
                    final sourceColor = _colorForSource(item.source);
                    final dateStr = DateFormat('MMM d, yyyy • HH:mm:ss')
                        .format(item.timestamp);

                    return IntrinsicHeight(
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // Left Line & Dot Indicator
                          Column(
                            children: [
                              Container(
                                width: 14,
                                height: 14,
                                decoration: BoxDecoration(
                                  color: sourceColor,
                                  shape: BoxShape.circle,
                                  border: Border.all(
                                    color: Colors.white,
                                    width: 2.5,
                                  ),
                                  boxShadow: [
                                    BoxShadow(
                                      color: sourceColor.withValues(alpha: 0.4),
                                      blurRadius: 4,
                                      spreadRadius: 1,
                                    ),
                                  ],
                                ),
                              ),
                              if (!isLast)
                                Expanded(
                                  child: Container(
                                    width: 2,
                                    color: AppColors.border,
                                  ),
                                ),
                            ],
                          ),
                          const SizedBox(width: 16),

                          // Right Content Card
                          Expanded(
                            child: Container(
                              margin: const EdgeInsets.only(bottom: 20),
                              padding: const EdgeInsets.all(14),
                              decoration: BoxDecoration(
                                color: Colors.white,
                                borderRadius: BorderRadius.circular(10),
                                border: Border.all(color: AppColors.border),
                              ),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisAlignment:
                                        MainAxisAlignment.spaceBetween,
                                    children: [
                                      Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 6,
                                          vertical: 2,
                                        ),
                                        decoration: BoxDecoration(
                                          color: sourceColor
                                              .withValues(alpha: 0.12),
                                          borderRadius:
                                              BorderRadius.circular(4),
                                        ),
                                        child: Text(
                                          _labelForSource(item.source),
                                          style: TextStyle(
                                            fontSize: 10,
                                            fontWeight: FontWeight.w700,
                                            color: sourceColor,
                                          ),
                                        ),
                                      ),
                                      Text(
                                        dateStr,
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: AppColors.textMuted,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  Text(
                                    item.title,
                                    style: const TextStyle(
                                      fontSize: 14,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.darkNeutral,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    item.description,
                                    style: const TextStyle(
                                      fontSize: 12,
                                      color: AppColors.textSecondary,
                                      height: 1.4,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}

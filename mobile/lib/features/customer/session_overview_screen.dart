import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import '../../core/constants/app_colors.dart';
import '../../state/customer_flow_provider.dart';
import 'invalid_token_screen.dart';

/// Customer verification session overview landing screen.
class SessionOverviewScreen extends StatefulWidget {
  final String token;

  const SessionOverviewScreen({super.key, required this.token});

  @override
  State<SessionOverviewScreen> createState() => _SessionOverviewScreenState();
}

class _SessionOverviewScreenState extends State<SessionOverviewScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<CustomerFlowProvider>().loadSession(widget.token);
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<CustomerFlowProvider>();

    if (provider.isLoading) {
      return Scaffold(
        appBar: AppBar(title: const Text('Refund Verification')),
        body: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(height: 16),
              Text(
                'Loading verification session...',
                style: TextStyle(color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
      );
    }

    if (provider.isTokenInvalid) {
      return InvalidTokenScreen(errorMessage: provider.errorMessage);
    }

    final overview = provider.overview;
    if (overview == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Refund Verification')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.error_outline_rounded,
                    size: 48, color: AppColors.assessmentInconsistent),
                const SizedBox(height: 16),
                Text(
                  provider.errorMessage ?? 'Unable to load verification session.',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 15),
                ),
                const SizedBox(height: 20),
                ElevatedButton(
                  onPressed: () => provider.loadSession(widget.token),
                  child: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final isCompleted = overview.status == 'COMPLETED';
    final isHeld = overview.status == 'HELD';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Refund Claim Verification'),
        automaticallyImplyLeading: false,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Held banner — customer cannot proceed while session is on hold
            if (isHeld) ...[
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppColors.statusHeldBg,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.statusHeld.withValues(alpha: 0.5)),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.pause_circle_filled_rounded,
                      color: AppColors.statusHeld,
                      size: 26,
                    ),
                    SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Verification Temporarily Paused',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: AppColors.darkNeutral,
                            ),
                          ),
                          SizedBox(height: 4),
                          Text(
                            'This verification has been temporarily paused by the merchant. No action is required from you right now. Please check back later or contact the merchant if you have questions.',
                            style: TextStyle(
                              fontSize: 13,
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
              const SizedBox(height: 16),
            ],

            // Completed banner if already submitted
            if (isCompleted) ...[

              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppColors.assessmentConsistentBg,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.assessmentConsistent),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.check_circle_rounded,
                      color: AppColors.assessmentConsistent,
                      size: 26,
                    ),
                    SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Verification Already Completed',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: AppColors.darkNeutral,
                            ),
                          ),
                          SizedBox(height: 4),
                          Text(
                            'Your verification evidence has already been submitted for this session. A verification session allows only one completed submission attempt.',
                            style: TextStyle(
                              fontSize: 13,
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
              const SizedBox(height: 16),
            ],

            // Merchant Banner
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppColors.primaryLight.withValues(alpha: 0.3),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: AppColors.primary.withValues(alpha: 0.3),
                ),
              ),
              child: Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.primary,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Icon(Icons.storefront_rounded,
                        color: Colors.white, size: 24),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          overview.merchant.businessName,
                          style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        if (overview.merchant.supportEmail != null)
                          Text(
                            overview.merchant.supportEmail!,
                            style: const TextStyle(
                              fontSize: 12,
                              color: AppColors.textSecondary,
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            // Product Details Card
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.inventory_2_outlined,
                            size: 18, color: AppColors.primary),
                        SizedBox(width: 8),
                        Text(
                          'Claimed Item',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ],
                    ),
                    const Divider(height: 20),
                    Text(
                      overview.product.name,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.darkNeutral,
                      ),
                    ),
                    const SizedBox(height: 6),
                    if (overview.product.sku != null)
                      Text(
                        'SKU: ${overview.product.sku}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textSecondary,
                        ),
                      ),
                    if (overview.product.category != null)
                      Text(
                        'Category: ${overview.product.category}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textSecondary,
                        ),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 14),

            // Guided Steps Info
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Row(
                      children: [
                        Icon(Icons.checklist_rounded,
                            size: 18, color: AppColors.primary),
                        SizedBox(width: 8),
                        Text(
                          'Verification Steps',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                      ],
                    ),
                    const Divider(height: 20),
                    Text(
                      overview.workflow.workflowName,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      isCompleted
                          ? 'Verification submitted. No further input required.'
                          : '${overview.workflow.totalSteps} guided steps will help verify your item condition.',
                      style: const TextStyle(
                        fontSize: 13,
                        color: AppColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 28),

            // Start or View Confirmation Button
            if (isCompleted) ...[
              ElevatedButton.icon(
                onPressed: () =>
                    context.go('/verify/${widget.token}/completed'),
                icon: const Icon(Icons.check_circle_outline_rounded, size: 20),
                label: const Text('View Submission Details'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.assessmentConsistent,
                  foregroundColor: Colors.white,
                ),
              ),
            ] else if (isHeld) ...[
              // Session is on hold — customer cannot start verification
              ElevatedButton(
                onPressed: null, // disabled
                style: ElevatedButton.styleFrom(
                  disabledBackgroundColor: AppColors.statusHeldBg,
                  disabledForegroundColor: AppColors.statusHeld,
                ),
                child: const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(Icons.pause_circle_outline_rounded, size: 18),
                    SizedBox(width: 8),
                    Text('Verification On Hold'),
                  ],
                ),
              ),
            ] else ...[
              ElevatedButton(
                onPressed: provider.isSubmitting
                    ? null
                    : () async {
                        final success = await provider.startSession();
                        if (success && context.mounted) {
                          context.go('/verify/${widget.token}/workflow');
                        }
                      },
                child: provider.isSubmitting
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor:
                              AlwaysStoppedAnimation<Color>(Colors.white),
                        ),
                      )
                    : const Text('Start Verification'),
              ),
            ],

          ],
        ),
      ),
    );
  }
}

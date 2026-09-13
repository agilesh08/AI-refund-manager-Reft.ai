import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_colors.dart';
import '../../services/merchant_service.dart';

/// Configurable refund scenario model.
class BuilderScenario {
  String id;
  String title;
  List<String> followUpQuestions;

  BuilderScenario({
    required this.id,
    required this.title,
    required this.followUpQuestions,
  });
}

/// Visual Merchant Workflow Builder ("Build Your Refund Verification").
class WorkflowBuilderScreen extends StatefulWidget {
  const WorkflowBuilderScreen({super.key});

  @override
  State<WorkflowBuilderScreen> createState() => _WorkflowBuilderScreenState();
}

class _WorkflowBuilderScreenState extends State<WorkflowBuilderScreen> {
  final MerchantService _merchantService = MerchantService();
  bool _isSaving = false;
  String _workflowName = 'Standard Refund Verification';

  // Configured scenarios with up to 3 follow-up questions
  final List<BuilderScenario> _scenarios = [
    BuilderScenario(
      id: 'damaged',
      title: 'Product arrived damaged',
      followUpQuestions: [
        'Please capture a closer photo showing the crack or damage clearly.',
        'Is the shipping box also crushed, torn, or wet?',
        'Please photograph the serial number or model barcode label.',
      ],
    ),
    BuilderScenario(
      id: 'defective',
      title: 'Defective or not functioning',
      followUpQuestions: [
        'Does the item power on or display any status indicator lights?',
        'Please photograph the power connection or accessories used.',
      ],
    ),
    BuilderScenario(
      id: 'missing_parts',
      title: 'Missing item or accessories',
      followUpQuestions: [
        'Please photograph all items and packaging received in the box.',
        'Was the outer courier tape broken or tampered with?',
      ],
    ),
    BuilderScenario(
      id: 'wrong_item',
      title: 'Received wrong product or variant',
      followUpQuestions: [
        'Please photograph the product label showing the model or barcode.',
        'Does the item match the description on your order receipt?',
      ],
    ),
  ];

  // Configured verification step toggles
  bool _includePaymentVerification = true;
  bool _includeOrderVerification = true;
  bool _includeDeliveryVerification = true;
  bool _includeLocationVerification = false;
  final TextEditingController _expectedPaymentAccountController =
      TextEditingController();

  @override
  void dispose() {
    _expectedPaymentAccountController.dispose();
    super.dispose();
  }

  void _addScenario() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Add Refund Scenario'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            hintText: 'e.g. Broken screen, Defective charging port',
            labelText: 'Scenario Title',
          ),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final text = controller.text.trim();
              if (text.isNotEmpty) {
                setState(() {
                  _scenarios.add(
                    BuilderScenario(
                      id: text.toLowerCase().replaceAll(RegExp(r'\s+'), '_'),
                      title: text,
                      followUpQuestions: [
                        'Please capture a photo clearly highlighting this issue.',
                      ],
                    ),
                  );
                });
                Navigator.pop(ctx);
              }
            },
            child: const Text('Add'),
          ),
        ],
      ),
    );
  }

  void _addFollowUpQuestion(BuilderScenario scenario) {
    if (scenario.followUpQuestions.length >= 3) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Maximum 3 follow-up questions allowed per scenario.'),
        ),
      );
      return;
    }

    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Add Follow-Up Question'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Scenario: "${scenario.title}"',
              style: const TextStyle(
                fontSize: 12,
                color: AppColors.textSecondary,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                hintText: 'e.g. Please take a photo of the product barcode',
                labelText: 'Targeted Question',
              ),
              maxLines: 2,
              autofocus: true,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              final text = controller.text.trim();
              if (text.isNotEmpty) {
                setState(() {
                  scenario.followUpQuestions.add(text);
                });
                Navigator.pop(ctx);
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  Future<void> _saveAndPublishWorkflow() async {
    setState(() => _isSaving = true);

    try {
      // 1. Create draft workflow
      final wf = await _merchantService.createWorkflow(
        _workflowName,
        description:
            'Configured verification workflow with ${_scenarios.length} scenarios and adaptive follow-ups',
      );
      final wfId = wf['id'] as String;

      int order = 1;

      // Step 1: Refund Reason Selection (Scenarios + follow-ups config)
      final optionsConfig = _scenarios
          .map((s) => {
                'value': s.id,
                'label': s.title,
                'follow_up_questions': s.followUpQuestions,
              })
          .toList();

      await _merchantService.addWorkflowStep(
        workflowId: wfId,
        stepKey: 'step_refund_reason',
        stepType: 'MCQ',
        title: 'Select Refund Reason',
        description: 'Choose the option that best describes the issue with your item.',
        stepOrder: order++,
        required: true,
        config: {'options': optionsConfig},
      );

      // Step 2: Camera-Only Initial Proof
      await _merchantService.addWorkflowStep(
        workflowId: wfId,
        stepKey: 'step_initial_proof',
        stepType: 'CAMERA',
        title: 'Show Us the Issue',
        description: 'Take a clear photograph of the item condition using your camera.',
        stepOrder: order++,
        required: true,
        config: {
          'camera_only': true,
          'allow_gallery': false,
          'tips': [
            'Keep entire product visible in the frame',
            'Ensure good lighting and avoid glare',
            'Focus on the specific damage or issue',
            'Keep the device steady while taking the photo',
          ],
        },
      );

      // Optional: Payment Verification (Account identifier, NO CVV / passwords)
      if (_includePaymentVerification) {
        final expectedAccount = _expectedPaymentAccountController.text.trim();
        await _merchantService.addWorkflowStep(
          workflowId: wfId,
          stepKey: 'step_payment_confirm',
          stepType: 'PAYMENT',
          title: 'Payment Account Confirmation',
          description: 'Confirm your payment account identifier for refund processing (no CVV/passwords requested).',
          stepOrder: order++,
          required: false,
          config: {
            'verify_account_id': true,
            if (expectedAccount.isNotEmpty) 'expected_payment_account': expectedAccount,
          },
        );
      }

      // Optional: Order Verification
      if (_includeOrderVerification) {
        await _merchantService.addWorkflowStep(
          workflowId: wfId,
          stepKey: 'step_order_confirm',
          stepType: 'ORDER',
          title: 'Order Details Verification',
          description: 'Confirm order receipt or tracking number matching this purchase.',
          stepOrder: order++,
          required: false,
        );
      }

      // Optional: Delivery Verification
      if (_includeDeliveryVerification) {
        await _merchantService.addWorkflowStep(
          workflowId: wfId,
          stepKey: 'step_delivery_confirm',
          stepType: 'DELIVERY',
          title: 'Package Delivery Condition',
          description: 'Confirm delivery condition and courier packaging status.',
          stepOrder: order++,
          required: false,
        );
      }

      // 3. Publish workflow
      await _merchantService.publishWorkflow(wfId);

      setState(() => _isSaving = false);

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            backgroundColor: AppColors.assessmentConsistent,
            content: Text('Workflow saved and published successfully!'),
          ),
        );
        context.go('/dashboard');
      }
    } catch (e) {
      setState(() => _isSaving = false);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            backgroundColor: AppColors.assessmentInconsistent,
            content: Text('Failed to save workflow: $e'),
          ),
        );
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
        title: const Text('Build Refund Verification'),
        actions: [
          IconButton(
            icon: const Icon(Icons.check_rounded),
            tooltip: 'Publish Workflow',
            onPressed: _isSaving ? null : _saveAndPublishWorkflow,
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Header Info Card
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppColors.primaryLight.withValues(alpha: 0.25),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: AppColors.primary.withValues(alpha: 0.3)),
              ),
              child: const Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.tune_rounded, color: AppColors.primary, size: 20),
                      SizedBox(width: 8),
                      Text(
                        'Verification Workflow Builder',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.darkNeutral,
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: 6),
                  Text(
                    'Configure customer claim scenarios, targeted follow-up questions, and mandatory camera-only proof steps.',
                    style: TextStyle(fontSize: 13, color: AppColors.textSecondary),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            // Workflow Name
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Workflow Title',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 6),
                    TextFormField(
                      initialValue: _workflowName,
                      onChanged: (val) => _workflowName = val,
                      decoration: const InputDecoration(
                        isDense: true,
                        hintText: 'e.g. Standard Electronics Verification',
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 20),

            // Section 1: Refund Scenarios & Follow-Up Questions
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text(
                  'Refund Scenarios & Questions',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.darkNeutral,
                  ),
                ),
                TextButton.icon(
                  onPressed: _addScenario,
                  icon: const Icon(Icons.add_rounded, size: 18),
                  label: const Text('Add Scenario'),
                ),
              ],
            ),
            const SizedBox(height: 8),

            ..._scenarios.asMap().entries.map((entry) {
              final idx = entry.key;
              final scenario = entry.value;

              return Card(
                margin: const EdgeInsets.only(bottom: 12),
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.all(6),
                            decoration: BoxDecoration(
                              color: AppColors.primaryLight,
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              '${idx + 1}',
                              style: const TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: AppColors.primary,
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              scenario.title,
                              style: const TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                                color: AppColors.darkNeutral,
                              ),
                            ),
                          ),
                          if (_scenarios.length > 1)
                            IconButton(
                              icon: const Icon(Icons.delete_outline_rounded,
                                  size: 20, color: AppColors.assessmentInconsistent),
                              onPressed: () {
                                setState(() => _scenarios.removeAt(idx));
                              },
                              tooltip: 'Remove scenario',
                            ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      Text(
                        'Targeted Follow-Up Questions (${scenario.followUpQuestions.length}/3):',
                        style: const TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.textSecondary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      ...scenario.followUpQuestions.asMap().entries.map((qEntry) {
                        final qIdx = qEntry.key;
                        final qText = qEntry.value;
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Padding(
                                padding: EdgeInsets.only(top: 4, right: 6),
                                child: Icon(Icons.arrow_right_rounded,
                                    size: 16, color: AppColors.primary),
                              ),
                              Expanded(
                                child: Text(
                                  qText,
                                  style: const TextStyle(
                                    fontSize: 13,
                                    color: AppColors.darkNeutral,
                                  ),
                                ),
                              ),
                              if (scenario.followUpQuestions.length > 1)
                                InkWell(
                                  onTap: () {
                                    setState(() {
                                      scenario.followUpQuestions.removeAt(qIdx);
                                    });
                                  },
                                  child: const Padding(
                                    padding: EdgeInsets.all(4),
                                    child: Icon(Icons.close_rounded,
                                        size: 14, color: AppColors.textMuted),
                                  ),
                                ),
                            ],
                          ),
                        );
                      }),
                      if (scenario.followUpQuestions.length < 3) ...[
                        const SizedBox(height: 4),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: () => _addFollowUpQuestion(scenario),
                            icon: const Icon(Icons.add_comment_outlined, size: 14),
                            label: const Text(
                              'Add Question',
                              style: TextStyle(fontSize: 12),
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              );
            }),
            const SizedBox(height: 20),

            // Section 2: Verification Steps Configuration (Numbered Step Cards)
            const Text(
              'Pipeline Steps',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.darkNeutral,
              ),
            ),
            const SizedBox(height: 10),

            // Step 01: Refund Reason
            _buildPipelineStepCard(
              number: '01',
              icon: Icons.format_list_bulleted_rounded,
              title: 'Refund Reason',
              description: 'Customer selects the claim reason and details.',
              badgeText: 'MANDATORY',
              badgeColor: AppColors.primary,
            ),
            const SizedBox(height: 10),

            // Step 02: Initial Evidence
            _buildPipelineStepCard(
              number: '02',
              icon: Icons.camera_alt_rounded,
              title: 'Initial Evidence',
              description: 'Customer captures live product proof via camera (no gallery).',
              badgeText: 'MANDATORY',
              badgeColor: AppColors.primary,
            ),
            const SizedBox(height: 10),

            // Step 03: Visual AI
            _buildPipelineStepCard(
              number: '03',
              icon: Icons.auto_awesome_rounded,
              title: 'Visual AI',
              description: 'Evidence is analyzed against trusted product baselines.',
              badgeText: 'AUTOMATIC',
              badgeColor: AppColors.assessmentConsistent,
            ),
            const SizedBox(height: 10),

            // Step 04: Targeted Follow-up
            _buildPipelineStepCard(
              number: '04',
              icon: Icons.help_outline_rounded,
              title: 'Targeted Follow-up',
              description: 'Additional proof may be requested adaptively.',
              badgeText: 'ADAPTIVE',
              badgeColor: AppColors.assessmentReviewRequired,
            ),
            const SizedBox(height: 10),

            // Step 05: Transaction Checks Card
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: AppColors.border, width: 0.9),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.015),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppColors.primaryLight.withValues(alpha: 0.5),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text(
                          '05',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w800,
                            color: AppColors.primary,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      const Icon(Icons.sync_alt_rounded,
                          color: AppColors.primary, size: 18),
                      const SizedBox(width: 8),
                      const Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Transaction Checks',
                              style: TextStyle(
                                fontSize: 14,
                                fontWeight: FontWeight.w700,
                                color: AppColors.darkNeutral,
                              ),
                            ),
                            Text(
                              'Payment, order, and delivery cross-signals.',
                              style: TextStyle(
                                fontSize: 11.5,
                                color: AppColors.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  const Divider(height: 1),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('Payment Account Check',
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                    subtitle: const Text('Verify account identifier only (no CVV/passwords)',
                        style: TextStyle(fontSize: 11)),
                    value: _includePaymentVerification,
                    onChanged: (val) =>
                        setState(() => _includePaymentVerification = val),
                  ),
                  if (_includePaymentVerification) ...[
                    Padding(
                      padding: const EdgeInsets.only(top: 4, bottom: 10),
                      child: TextField(
                        controller: _expectedPaymentAccountController,
                        decoration: const InputDecoration(
                          labelText: 'Merchant Payment Account / UPI ID',
                          hintText: 'e.g. alithastore@upi or merchant business name',
                          helperText: 'Customer payment proof payee will be matched against this',
                          prefixIcon: Icon(Icons.account_balance_wallet_outlined, size: 18),
                          isDense: true,
                        ),
                        style: const TextStyle(fontSize: 13),
                      ),
                    ),
                  ],
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('Order Details Check',
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                    subtitle: const Text('Verify purchase record and receipt items',
                        style: TextStyle(fontSize: 11)),
                    value: _includeOrderVerification,
                    onChanged: (val) =>
                        setState(() => _includeOrderVerification = val),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('Delivery Condition Check',
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                    subtitle: const Text('Verify delivery condition and carrier package status',
                        style: TextStyle(fontSize: 11)),
                    value: _includeDeliveryVerification,
                    onChanged: (val) =>
                        setState(() => _includeDeliveryVerification = val),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('Location Consistency Check',
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                    subtitle: const Text('Verify delivery address proximity signals',
                        style: TextStyle(fontSize: 11)),
                    value: _includeLocationVerification,
                    onChanged: (val) =>
                        setState(() => _includeLocationVerification = val),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),

            // Publish Button
            ElevatedButton.icon(
              onPressed: _isSaving ? null : _saveAndPublishWorkflow,
              icon: _isSaving
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    )
                  : const Icon(Icons.rocket_launch_rounded),
              label: Text(_isSaving
                  ? 'Publishing Workflow...'
                  : 'Save & Publish Verification Workflow'),
              style: ElevatedButton.styleFrom(
                minimumSize: const Size(double.infinity, 50),
              ),
            ),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  Widget _buildPipelineStepCard({
    required String number,
    required IconData icon,
    required String title,
    required String description,
    required String badgeText,
    required Color badgeColor,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border, width: 0.9),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.015),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            decoration: BoxDecoration(
              color: AppColors.primaryLight.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              number,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: AppColors.primary,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Icon(icon, color: AppColors.primary, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.darkNeutral,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  description,
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
            decoration: BoxDecoration(
              color: badgeColor.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: badgeColor.withValues(alpha: 0.3)),
            ),
            child: Text(
              badgeText,
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                color: badgeColor,
              ),
            ),
          ),
        ],
      ),
    );
  }
}


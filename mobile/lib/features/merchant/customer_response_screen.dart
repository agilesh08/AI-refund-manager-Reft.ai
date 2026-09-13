import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../../core/constants/api_endpoints.dart';
import '../../core/constants/app_colors.dart';
import '../../core/storage/token_storage.dart';
import '../../models/evidence_models.dart';
import '../../models/report_models.dart';
import '../../shared/widgets/assessment_badge.dart';
import '../../shared/widgets/decision_badge.dart';
import '../../shared/widgets/status_badge.dart';
import '../../state/merchant_dashboard_provider.dart';

/// Dedicated Read-Only Merchant View of the Complete Customer Verification Journey.
class CustomerResponseScreen extends StatefulWidget {
  final String verificationId;

  const CustomerResponseScreen({super.key, required this.verificationId});

  @override
  State<CustomerResponseScreen> createState() => _CustomerResponseScreenState();
}

class _CustomerResponseScreenState extends State<CustomerResponseScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  String? _token;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this);
    _loadAuthToken();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<MerchantDashboardProvider>();
      if (provider.selectedVerification == null ||
          provider.selectedVerification!.verification['verification_id'] !=
              widget.verificationId) {
        provider.loadInvestigationDetail(widget.verificationId);
      }
    });
  }

  Future<void> _loadAuthToken() async {
    final t = await TokenStorage().getToken();
    if (mounted) {
      setState(() {
        _token = t;
      });
    }
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _openImageViewer(
    BuildContext context,
    EvidenceResponseModel evidence,
    Map<String, dynamic>? analysis,
  ) {
    final imageUrl = '${ApiEndpoints.verifications}/${widget.verificationId}/evidence/${evidence.id}';
    final headers = _token != null ? {'Authorization': 'Bearer $_token'} : null;

    showDialog(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.85),
      builder: (ctx) => EvidenceImageViewerDialog(
        evidence: evidence,
        analysis: analysis,
        imageUrl: imageUrl,
        headers: headers,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<MerchantDashboardProvider>(
      builder: (context, provider, child) {
        final detail = provider.selectedVerification;
        final isLoading = provider.isLoadingDetail && detail == null;

        final displayId = widget.verificationId.length > 12
            ? '${widget.verificationId.substring(0, 12)}...'
            : widget.verificationId;

        return Scaffold(
          backgroundColor: AppColors.background,
          appBar: AppBar(
            backgroundColor: Colors.white,
            elevation: 0.5,
            leading: IconButton(
              icon: const Icon(Icons.arrow_back, color: AppColors.darkNeutral),
              onPressed: () => context.pop(),
            ),
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Customer Response',
                  style: TextStyle(
                    fontSize: 16.5,
                    fontWeight: FontWeight.w700,
                    color: AppColors.darkNeutral,
                  ),
                ),
                Text(
                  'Verification: $displayId',
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.textSecondary,
                  ),
                ),
              ],
            ),
            bottom: TabBar(
              controller: _tabController,
              isScrollable: true,
              tabAlignment: TabAlignment.start,
              labelColor: AppColors.primary,
              unselectedLabelColor: AppColors.textSecondary,
              indicatorColor: AppColors.primary,
              indicatorWeight: 2.5,
              labelStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
              unselectedLabelStyle: const TextStyle(fontWeight: FontWeight.w500, fontSize: 13),
              tabs: const [
                Tab(icon: Icon(Icons.info_outline, size: 18), text: 'Initial Claim'),
                Tab(icon: Icon(Icons.quiz_outlined, size: 18), text: 'Workflow Q&A'),
                Tab(icon: Icon(Icons.photo_library_outlined, size: 18), text: 'Evidence Items'),
                Tab(icon: Icon(Icons.psychology_outlined, size: 18), text: 'Follow-Ups'),
                Tab(icon: Icon(Icons.timeline_outlined, size: 18), text: 'Audit Trail'),
              ],
            ),
          ),
          body: isLoading
              ? const Center(child: CircularProgressIndicator())
              : detail == null
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          const Icon(Icons.error_outline, size: 48, color: AppColors.textMuted),
                          const SizedBox(height: 12),
                          const Text('Failed to load customer response details'),
                          const SizedBox(height: 12),
                          ElevatedButton(
                            onPressed: () => provider.loadInvestigationDetail(widget.verificationId),
                            child: const Text('Retry'),
                          ),
                        ],
                      ),
                    )
                  : TabBarView(
                      controller: _tabController,
                      children: [
                        _buildInitialClaimTab(
                          customerName: detail.claim['customer_name']?.toString() ?? 'N/A',
                          customerContact: detail.claim['customer_contact']?.toString() ??
                              detail.verification['customer_email']?.toString() ??
                              'N/A',
                          orderId: detail.claim['order_id']?.toString() ??
                              detail.verification['order_id']?.toString() ??
                              'N/A',
                          refundReason: detail.claim['refund_reason']?.toString() ?? 'Unspecified',
                          refundAmount: detail.claim['refund_amount'] != null
                              ? '₹${detail.claim['refund_amount']}'
                              : '₹0.00',
                          customerMessage: detail.claim['customer_explanation']?.toString() ??
                              detail.claim['notes']?.toString() ??
                              '',
                          product: detail.product,
                          detail: detail,
                        ),
                        _buildWorkflowQnATab(detail),
                        _buildEvidenceTab(detail),
                        _buildFollowUpsTab(detail),
                        _buildTimelineTab(detail),
                      ],
                    ),
        );
      },
    );
  }

  Widget _buildInitialClaimTab({
    required String customerName,
    required String customerContact,
    required String orderId,
    required String refundReason,
    required String refundAmount,
    required String customerMessage,
    required Map<String, dynamic> product,
    required VerificationDetailDashboardModel detail,
  }) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: Row(
              children: [
                Icon(Icons.verified_user_outlined, size: 18, color: Colors.blue.shade800),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Read-only customer submission trail. Use Investigation view for merchant decisions.',
                    style: TextStyle(fontSize: 11.5, color: Colors.blue.shade900, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          _buildSectionCard(
            title: 'Customer Information',
            icon: Icons.person_outline_rounded,
            children: [
              _buildInfoRow('Customer Name', customerName),
              _buildInfoRow('Contact / Email', customerContact),
              _buildInfoRow('Order ID', '#$orderId'),
            ],
          ),
          const SizedBox(height: 14),
          _buildSectionCard(
            title: 'Claim Details',
            icon: Icons.receipt_long_outlined,
            children: [
              _buildInfoRow('Product Name', product['name']?.toString() ?? 'Unknown'),
              _buildInfoRow('Product SKU', product['sku']?.toString() ?? 'N/A'),
              _buildInfoRow('Refund Reason', refundReason, isHighlighted: true),
              _buildInfoRow('Claimed Amount', refundAmount),
              if (customerMessage.isNotEmpty) ...[
                const SizedBox(height: 8),
                const Text(
                  'Original Customer Statement:',
                  style: TextStyle(fontSize: 11.5, color: AppColors.textSecondary, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF9FAFC),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppColors.border, width: 0.8),
                  ),
                  child: Text(
                    customerMessage,
                    style: const TextStyle(fontSize: 12.5, color: AppColors.darkNeutral, height: 1.4),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 14),
          _buildSectionCard(
            title: 'Session Status',
            icon: Icons.shield_outlined,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Verification Status', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                  StatusBadge(status: detail.status),
                ],
              ),
              const SizedBox(height: 8),
              if (detail.fusionResult != null) ...[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('AI Assessment State', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                    AssessmentBadge(
                      assessmentState: detail.fusionResult!.assessmentState,
                      confidence: detail.fusionResult!.overallConfidence,
                    ),
                  ],
                ),
                const SizedBox(height: 8),
              ],
              if (detail.merchantDecision != null) ...[
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Merchant Decision', style: TextStyle(fontSize: 12, color: AppColors.textSecondary)),
                    DecisionBadge(decision: detail.merchantDecision!.decision),
                  ],
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildWorkflowQnATab(VerificationDetailDashboardModel detail) {
    final questions = detail.questionsAsked;
    final workflow = detail.workflow;
    final steps = (workflow['steps'] as List<dynamic>?) ?? [];

    if (questions.isEmpty && steps.isEmpty) {
      return _buildEmptyState(
        icon: Icons.help_outline_rounded,
        title: 'No Workflow Questions Configured',
        message: 'This verification session did not define structured workflow questions.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: questions.isNotEmpty ? questions.length : steps.length,
      itemBuilder: (context, index) {
        if (questions.isNotEmpty) {
          final q = questions[index];
          final title = q['title'] ?? q['step_key'] ?? 'Question ${index + 1}';
          final questionText = q['question'] ?? q['prompt'] ?? title;
          final answer = q['answer'] ?? q['customer_answer'];
          final stepType = (q['step_type'] ?? 'TEXT').toString().toUpperCase();
          final isAnswered = answer != null && answer.toString().trim().isNotEmpty;

          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppColors.border, width: 0.8),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: const Color(0xFFF0F4F8),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          stepType,
                          style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: AppColors.textSecondary),
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: isAnswered ? const Color(0xFFE8F5E9) : const Color(0xFFFFF3E0),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          isAnswered ? 'Answered' : 'Not answered',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w700,
                            color: isAnswered ? const Color(0xFF2E7D32) : const Color(0xFFE65100),
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    questionText.toString(),
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.darkNeutral),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF9FAFB),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
                    ),
                    child: Text(
                      isAnswered ? answer.toString() : 'No response provided by customer.',
                      style: TextStyle(
                        fontSize: 12,
                        color: isAnswered ? AppColors.darkNeutral : AppColors.textMuted,
                        fontStyle: isAnswered ? FontStyle.normal : FontStyle.italic,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        } else {
          final step = steps[index] as Map<String, dynamic>;
          final stepKey = step['step_key'] ?? 'Step ${index + 1}';
          final title = step['title'] ?? stepKey;
          final stepType = (step['step_type'] ?? 'TEXT').toString().toUpperCase();

          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppColors.border, width: 0.8),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        stepKey.toString(),
                        style: const TextStyle(fontSize: 11, color: AppColors.textSecondary, fontWeight: FontWeight.w600),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: const Color(0xFFF0F4F8),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text(
                          stepType,
                          style: const TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: AppColors.textSecondary),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    title.toString(),
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.darkNeutral),
                  ),
                ],
              ),
            ),
          );
        }
      },
    );
  }

  Widget _buildEvidenceTab(VerificationDetailDashboardModel detail) {
    final evidenceItems = detail.evidenceItems;
    final visualAnalyses = detail.visualAnalysisItems;

    final Map<String, Map<String, dynamic>> analysisMap = {};
    for (final a in visualAnalyses) {
      final evId = a['evidence_id'] ?? a['id'];
      if (evId != null) {
        analysisMap[evId.toString()] = a;
      }
    }

    if (evidenceItems.isEmpty) {
      return _buildEmptyState(
        icon: Icons.photo_library_outlined,
        title: 'No Evidence Uploaded',
        message: 'The customer has not yet uploaded photos or evidence for this claim.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: evidenceItems.length,
      itemBuilder: (context, index) {
        final ev = evidenceItems[index];
        final analysis = analysisMap[ev.id];
        final isImage = ev.evidenceType.toUpperCase().contains('IMAGE') ||
            ev.evidenceType.toUpperCase().contains('CAMERA');
        final uploadDateStr = ev.createdAt != null
            ? DateFormat('MMM d, yyyy • HH:mm').format(ev.createdAt!)
            : 'N/A';
        final imageUrl = '${ApiEndpoints.verifications}/${widget.verificationId}/evidence/${ev.id}';
        final headers = _token != null ? {'Authorization': 'Bearer $_token'} : null;

        return Card(
          margin: const EdgeInsets.only(bottom: 14),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: const BorderSide(color: AppColors.border, width: 0.8),
          ),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      isImage ? Icons.image_outlined : Icons.description_outlined,
                      size: 18,
                      color: AppColors.primary,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        ev.workflowStepKey ?? ev.evidenceType,
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.darkNeutral),
                      ),
                    ),
                    _buildStatusPill(ev.isDuplicate ? 'DUPLICATE' : 'UPLOADED'),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  'Uploaded $uploadDateStr • ID: ${ev.id}',
                  style: const TextStyle(fontSize: 10.5, color: AppColors.textMuted),
                ),
                const SizedBox(height: 10),
                if (isImage) ...[
                  InkWell(
                    onTap: () => _openImageViewer(context, ev, analysis),
                    borderRadius: BorderRadius.circular(8),
                    child: Container(
                      height: 180,
                      width: double.infinity,
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.04),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: AppColors.border, width: 0.8),
                      ),
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: Image.network(
                              imageUrl,
                              headers: headers,
                              fit: BoxFit.cover,
                              width: double.infinity,
                              height: 180,
                              errorBuilder: (ctx, err, stack) => _buildPlaceholderImage(),
                            ),
                          ),
                          Positioned(
                            bottom: 8,
                            right: 8,
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                              decoration: BoxDecoration(
                                color: Colors.black.withValues(alpha: 0.70),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.zoom_in, size: 14, color: Colors.white),
                                  SizedBox(width: 4),
                                  Text(
                                    'Tap to Inspect',
                                    style: TextStyle(fontSize: 10.5, color: Colors.white, fontWeight: FontWeight.w600),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ] else if (ev.textContent != null && ev.textContent!.isNotEmpty) ...[
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF9FAFB),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppColors.border, width: 0.8),
                    ),
                    child: Text(
                      ev.textContent!,
                      style: const TextStyle(fontSize: 12, color: AppColors.darkNeutral),
                    ),
                  ),
                ],
                if (analysis != null) ...[
                  const SizedBox(height: 10),
                  _buildAnalysisSnippet(analysis),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildFollowUpsTab(VerificationDetailDashboardModel detail) {
    final followUps = detail.adaptiveFollowUpQuestions;
    final requests = detail.adaptiveRequests;

    if (followUps.isEmpty && requests.isEmpty) {
      return _buildEmptyState(
        icon: Icons.question_answer_outlined,
        title: 'No Follow-Up Questions',
        message: 'The AI did not require additional evidence or follow-up questions for this session.',
      );
    }

    final totalCount = followUps.isNotEmpty ? followUps.length : requests.length;

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: totalCount,
      itemBuilder: (context, index) {
        if (followUps.isNotEmpty) {
          final f = followUps[index];
          final qNum = index + 1;
          final question = f['question'] ?? f['reason'] ?? 'Follow-up question $qNum';
          final response = f['customer_response'] ?? f['answer'] ?? 'Awaiting customer response';
          final observation = f['ai_observation'] ?? f['findings'];

          return Card(
            margin: const EdgeInsets.only(bottom: 14),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppColors.border, width: 0.8),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      CircleAvatar(
                        radius: 12,
                        backgroundColor: AppColors.primary,
                        child: Text('$qNum', style: const TextStyle(fontSize: 11, color: Colors.white, fontWeight: FontWeight.w700)),
                      ),
                      const SizedBox(width: 8),
                      Text('Adaptive Follow-up #$qNum', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                    ],
                  ),
                  const SizedBox(height: 10),
                  const Text('AI Question / Instruction:', style: TextStyle(fontSize: 11, color: AppColors.textSecondary, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF4F6F9),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(question.toString(), style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: AppColors.darkNeutral)),
                  ),
                  const SizedBox(height: 10),
                  const Text('Customer Response:', style: TextStyle(fontSize: 11, color: AppColors.textSecondary, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF9FAFB),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
                    ),
                    child: Text(response.toString(), style: const TextStyle(fontSize: 12, color: AppColors.darkNeutral)),
                  ),
                  if (observation != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        color: Colors.amber.shade50,
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: Colors.amber.shade200),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.visibility_outlined, size: 15, color: Colors.amber.shade900),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              'Visual finding: $observation',
                              style: TextStyle(fontSize: 11, color: Colors.amber.shade900, fontWeight: FontWeight.w600),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        } else {
          final req = requests[index];
          final qNum = index + 1;
          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: const BorderSide(color: AppColors.border, width: 0.8),
            ),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Follow-up Request #$qNum (${req.requestedEvidenceType})', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  Text('Reason: ${req.reason}', style: const TextStyle(fontSize: 12, color: AppColors.darkNeutral)),
                  const SizedBox(height: 4),
                  Text('Status: ${req.status}', style: const TextStyle(fontSize: 11, color: AppColors.textSecondary)),
                ],
              ),
            ),
          );
        }
      },
    );
  }

  Widget _buildTimelineTab(VerificationDetailDashboardModel detail) {
    final timeline = detail.timeline;

    if (timeline.isEmpty) {
      return _buildEmptyState(
        icon: Icons.timeline_outlined,
        title: 'No Audit Events',
        message: 'No timeline events recorded yet for this verification session.',
      );
    }

    final dateFormat = DateFormat('MMM d • HH:mm:ss');

    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: timeline.length,
      itemBuilder: (context, index) {
        final event = timeline[index];
        final eventDate = dateFormat.format(event.timestamp);
        final sourceColor = _getColorForSource(event.source);

        return IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Timeline vertical indicator
              Column(
                children: [
                  Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      color: sourceColor,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 2),
                      boxShadow: [
                        BoxShadow(
                          color: sourceColor.withValues(alpha: 0.4),
                          blurRadius: 4,
                        ),
                      ],
                    ),
                  ),
                  if (index < timeline.length - 1)
                    Expanded(
                      child: Container(
                        width: 2,
                        color: AppColors.border,
                      ),
                    ),
                ],
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: AppColors.border, width: 0.8),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: sourceColor.withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                event.source.replaceAll('_', ' '),
                                style: TextStyle(
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w700,
                                  color: sourceColor,
                                ),
                              ),
                            ),
                            Text(
                              eventDate,
                              style: const TextStyle(fontSize: 10.5, color: AppColors.textMuted),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          event.title.isNotEmpty ? event.title : event.eventType.replaceAll('_', ' '),
                          style: const TextStyle(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w700,
                            color: AppColors.darkNeutral,
                          ),
                        ),
                        if (event.description.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text(
                            event.description,
                            style: const TextStyle(fontSize: 11.5, color: AppColors.textSecondary),
                          ),
                        ],
                        if (event.metadata.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: const Color(0xFFF9FAFC),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Text(
                              event.metadata.entries
                                  .where((e) => e.key != 'raw_data' && e.value != null)
                                  .map((e) => '${e.key}: ${e.value}')
                                  .join('\n'),
                              style: const TextStyle(
                                fontSize: 11,
                                fontFamily: 'monospace',
                                color: AppColors.darkNeutral,
                              ),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSectionCard({
    required String title,
    required IconData icon,
    required List<Widget> children,
  }) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border, width: 0.8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 17, color: AppColors.primary),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.darkNeutral)),
            ],
          ),
          const Divider(height: 18, thickness: 0.6),
          ...children,
        ],
      ),
    );
  }

  Widget _buildInfoRow(String label, String value, {bool isHighlighted = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: TextStyle(
                fontSize: 12,
                fontWeight: isHighlighted ? FontWeight.w800 : FontWeight.w600,
                color: isHighlighted ? AppColors.primary : AppColors.darkNeutral,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusPill(String status) {
    Color bg = const Color(0xFFE8F5E9);
    Color fg = const Color(0xFF2E7D32);
    if (status == 'FAILED') {
      bg = const Color(0xFFFFEBEE);
      fg = const Color(0xFFC62828);
    } else if (status == 'READY_FOR_ANALYSIS' || status == 'UPLOADED') {
      bg = const Color(0xFFE3F2FD);
      fg = const Color(0xFF1565C0);
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(12)),
      child: Text(status, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: fg)),
    );
  }

  Widget _buildAnalysisSnippet(Map<String, dynamic> analysis) {
    final status = analysis['status'] ?? 'UNKNOWN';
    final result = analysis['result'] ?? analysis['result_json'] ?? {};
    final capture = result['capture_assessment'] ?? result['evidence_capture_assessment'] ?? {};
    final captureType = capture['type'] ?? 'UNCLEAR';
    final isScreen = captureType.toString().contains('SCREEN');

    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: status == 'COMPLETED' ? (isScreen ? Colors.orange.shade50 : Colors.blue.shade50) : Colors.red.shade50,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: status == 'COMPLETED' ? (isScreen ? Colors.orange.shade200 : Colors.blue.shade200) : Colors.red.shade200,
          width: 0.8,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                status == 'COMPLETED' ? (isScreen ? Icons.tv_outlined : Icons.check_circle_outline) : Icons.error_outline,
                size: 15,
                color: status == 'COMPLETED' ? (isScreen ? Colors.orange.shade800 : Colors.blue.shade800) : Colors.red.shade800,
              ),
              const SizedBox(width: 6),
              Text(
                'AI Visual Analysis: $status',
                style: TextStyle(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w700,
                  color: status == 'COMPLETED' ? (isScreen ? Colors.orange.shade900 : Colors.blue.shade900) : Colors.red.shade900,
                ),
              ),
            ],
          ),
          if (captureType != 'UNCLEAR') ...[
            const SizedBox(height: 4),
            Text(
              'Capture Appearance: ${captureType.toString().replaceAll("_", " ")}',
              style: TextStyle(fontSize: 11, color: isScreen ? Colors.orange.shade900 : Colors.blue.shade900, fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPlaceholderImage() {
    return Container(
      color: Colors.grey.shade100,
      alignment: Alignment.center,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.image_outlined, size: 36, color: Colors.grey.shade400),
          const SizedBox(height: 6),
          Text('Evidence Image', style: TextStyle(fontSize: 11, color: Colors.grey.shade500)),
        ],
      ),
    );
  }

  Widget _buildEmptyState({
    required IconData icon,
    required String title,
    required String message,
  }) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 48, color: AppColors.textMuted),
            const SizedBox(height: 12),
            Text(title, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: AppColors.darkNeutral)),
            const SizedBox(height: 6),
            Text(message, textAlign: TextAlign.center, style: const TextStyle(fontSize: 12, color: AppColors.textSecondary)),
          ],
        ),
      ),
    );
  }

  Color _getColorForSource(String source) {
    switch (source.toUpperCase()) {
      case 'MERCHANT':
        return AppColors.primary;
      case 'CUSTOMER':
        return const Color(0xFF2E7D32);
      case 'GEMINI_VISION':
      case 'SYSTEM_GEMINI_VISION':
        return const Color(0xFF1565C0);
      case 'LLAMA_REASONING':
        return const Color(0xFF6A1B9A);
      default:
        return const Color(0xFF546E7A);
    }
  }
}

/// Fullscreen Dialog for In-Depth Evidence Inspection with Concise Gemini Observations.
class EvidenceImageViewerDialog extends StatelessWidget {
  final EvidenceResponseModel evidence;
  final Map<String, dynamic>? analysis;
  final String? imageUrl;
  final Map<String, String>? headers;

  const EvidenceImageViewerDialog({
    super.key,
    required this.evidence,
    this.analysis,
    this.imageUrl,
    this.headers,
  });

  @override
  Widget build(BuildContext context) {
    final result = analysis?['result'] ?? analysis?['result_json'] ?? {};
    final capture = result['capture_assessment'] ?? result['evidence_capture_assessment'] ?? {};
    final captureType = capture['type'] ?? 'UNCLEAR';
    final captureConfidence = (capture['confidence'] as num?)?.toDouble();
    final captureObservations = (capture['observations'] as List<dynamic>?) ?? [];

    final identity = result['product_identity'] ?? {};
    final apparentProduct = identity['apparent_product_type'] ?? 'Not identified';
    final matchesTrusted = identity['matches_trusted_product'];

    final quality = result['image_quality'] ?? {};
    final qualityOverall = quality['overall'] ?? (quality['is_clear'] == true ? 'GOOD' : 'POOR');
    final qualityIssues = (quality['issues'] as List<dynamic>?) ?? [];

    final observations = (result['key_visual_observations'] as List<dynamic>?) ?? [];

    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Stack(
        children: [
          Positioned.fill(
            child: InteractiveViewer(
              minScale: 0.8,
              maxScale: 4.0,
              child: Center(
                child: (imageUrl != null && imageUrl!.isNotEmpty)
                    ? Image.network(
                        imageUrl!,
                        headers: headers,
                        fit: BoxFit.contain,
                        errorBuilder: (ctx, err, stack) => const Center(
                          child: Icon(Icons.broken_image, size: 64, color: Colors.white54),
                        ),
                      )
                    : const Center(
                        child: Icon(Icons.image_not_supported, size: 64, color: Colors.white54),
                      ),
              ),
            ),
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(16, 44, 16, 12),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Colors.black.withValues(alpha: 0.7), Colors.transparent],
                ),
              ),
              child: Row(
                children: [
                  IconButton(
                    icon: const Icon(Icons.close, color: Colors.white, size: 24),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          evidence.workflowStepKey ?? 'Evidence Inspection',
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: Colors.white),
                        ),
                        Text(
                          'ID: ${evidence.id}',
                          style: const TextStyle(fontSize: 11, color: Colors.white70),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (analysis != null)
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: Container(
                constraints: const BoxConstraints(maxHeight: 320),
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: const Color(0xFF1E242B).withValues(alpha: 0.95),
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(16)),
                  boxShadow: [
                    BoxShadow(color: Colors.black.withValues(alpha: 0.4), blurRadius: 10, offset: const Offset(0, -2)),
                  ],
                ),
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          const Row(
                            children: [
                              Icon(Icons.visibility_rounded, size: 16, color: Colors.lightBlueAccent),
                              SizedBox(width: 6),
                              Text(
                                'Gemini Visual Observations',
                                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: Colors.white),
                              ),
                            ],
                          ),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2.5),
                            decoration: BoxDecoration(
                              color: analysis!['status'] == 'COMPLETED' ? Colors.green.shade800 : Colors.red.shade800,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: Text(
                              analysis!['status']?.toString() ?? 'COMPLETED',
                              style: const TextStyle(fontSize: 9.5, color: Colors.white, fontWeight: FontWeight.w700),
                            ),
                          ),
                        ],
                      ),
                      const Divider(height: 16, color: Colors.white24),
                      if (captureType != 'UNCLEAR') ...[
                        Row(
                          children: [
                            const Text('Capture Method: ', style: TextStyle(fontSize: 11.5, color: Colors.white70)),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: captureType.toString().contains('SCREEN') ? Colors.amber.shade900 : Colors.blue.shade900,
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                captureType.toString().replaceAll('_', ' '),
                                style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: Colors.white),
                              ),
                            ),
                            if (captureConfidence != null)
                              Text(' (${(captureConfidence * 100).toInt()}%)', style: const TextStyle(fontSize: 11, color: Colors.white60)),
                          ],
                        ),
                        if (captureObservations.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              captureObservations.join(' • '),
                              style: const TextStyle(fontSize: 11, color: Colors.white60),
                            ),
                          ),
                        const SizedBox(height: 8),
                      ],
                      if (apparentProduct != 'Not identified') ...[
                        Row(
                          children: [
                            const Text('Apparent Product: ', style: TextStyle(fontSize: 11.5, color: Colors.white70)),
                            Text(apparentProduct.toString(), style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: Colors.white)),
                            if (matchesTrusted != null) ...[
                              const SizedBox(width: 8),
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                decoration: BoxDecoration(
                                  color: matchesTrusted == 'MATCH' ? Colors.green.shade900 : Colors.red.shade900,
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text(matchesTrusted.toString(), style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Colors.white)),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 8),
                      ],
                      Row(
                        children: [
                          const Text('Image Quality: ', style: TextStyle(fontSize: 11.5, color: Colors.white70)),
                          Text(qualityOverall.toString(), style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: Colors.white)),
                          if (qualityIssues.isNotEmpty)
                            Text(' • Issues: ${qualityIssues.join(", ")}', style: const TextStyle(fontSize: 11, color: Colors.white60)),
                        ],
                      ),
                      if (observations.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        ...observations.take(3).map((obs) => Padding(
                              padding: const EdgeInsets.only(bottom: 3),
                              child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Text('• ', style: TextStyle(color: Colors.lightBlueAccent, fontSize: 12)),
                                  Expanded(
                                    child: Text(obs.toString(), style: const TextStyle(fontSize: 11, color: Colors.white70)),
                                  ),
                                ],
                              ),
                            )),
                      ],
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

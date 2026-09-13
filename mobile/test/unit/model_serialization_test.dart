import 'package:flutter_test/flutter_test.dart';
import 'package:refund_verification_app/models/auth_models.dart';
import 'package:refund_verification_app/models/customer_verification.dart';
import 'package:refund_verification_app/models/evidence_models.dart';
import 'package:refund_verification_app/models/fusion_models.dart';
import 'package:refund_verification_app/models/merchant_decision_models.dart';
import 'package:refund_verification_app/models/report_models.dart';
import 'package:refund_verification_app/models/signal_models.dart';
import 'package:refund_verification_app/models/workflow_step.dart';
import '../mocks/mock_data.dart';

void main() {
  group('Model Serialization Tests', () {
    test('AuthModels: LoginRequest and AuthTokens', () {
      final req = LoginRequest(email: 'test@merchant.com', password: 'password123');
      final json = req.toJson();
      expect(json['email'], 'test@merchant.com');
      expect(json['password'], 'password123');

      final tokens = AuthTokens.fromJson({
        'access_token': 'jwt_secret_token_123',
        'token_type': 'bearer',
      });
      expect(tokens.accessToken, 'jwt_secret_token_123');
      expect(tokens.tokenType, 'bearer');
    });

    test('CustomerVerificationResponse parses correctly', () {
      final res = CustomerVerificationResponse.fromJson(MockData.customerVerificationJson);
      expect(res.verificationId, 'sess_12345');
      expect(res.merchant.businessName, 'Acme Electronics');
      expect(res.merchant.supportEmail, 'support@acme.com');
      expect(res.product.name, 'Noise Cancelling Headphones X');
      expect(res.product.sku, 'NCH-100');
      expect(res.status, 'CREATED');
      expect(res.workflow.totalSteps, 4);
    });

    test('CustomerWorkflowResponse parses steps and configs', () {
      final res = CustomerWorkflowResponse.fromJson(MockData.workflowJson);
      expect(res.verificationId, 'sess_12345');
      expect(res.steps.length, 3);

      final photoStep = res.steps[0];
      expect(photoStep.stepKey, 'step_photo');
      expect(photoStep.stepType, 'IMAGE');
      expect(photoStep.required, true);

      final mcqStep = res.steps[1];
      expect(mcqStep.stepType, 'MCQ');
      expect(mcqStep.mcqChoices.length, 3);
      expect(mcqStep.mcqChoices[0], 'Yes, completely intact');

      final textStep = res.steps[2];
      expect(textStep.stepType, 'TEXT');
      expect(textStep.placeholder, 'Details...');
    });

    test('EvidenceResponseModel and Adaptive Request', () {
      final ev = EvidenceResponseModel.fromJson({
        'id': 'ev_123',
        'verification_session_id': 'sess_12345',
        'evidence_type': 'CUSTOMER_IMAGE',
        'original_filename': 'photo.jpg',
        'file_size_bytes': 204800,
        'sha256_hash': 'abcdef1234567890',
        'is_duplicate': false,
        'workflow_step_key': 'step_photo',
      });
      expect(ev.id, 'ev_123');
      expect(ev.evidenceType, 'CUSTOMER_IMAGE');
      expect(ev.isDuplicate, false);

      final req = CustomerEvidenceRequestModel.fromJson({
        'id': 'req_456',
        'verification_session_id': 'sess_12345',
        'requested_step_key': 'step_photo',
        'prompt_text': 'Please re-photograph serial number in brighter light.',
        'status': 'PENDING',
      });
      expect(req.id, 'req_456');
      expect(req.isPending, true);
      expect(req.isFulfilled, false);
    });

    test('Signals and Fusion Models', () {
      final signal = CustomerSignalModel.fromJson({
        'id': 'sig_1',
        'signal_type': 'PAYMENT',
        'source_type': 'STRIPE',
        'status': 'VERIFIED',
        'summary': {'amount': 129.99},
      });
      expect(signal.signalType, 'PAYMENT');
      expect(signal.status, 'VERIFIED');

      final fusion = FusionResponseModel.fromJson(MockData.fusionJson);
      expect(fusion.id, 'fusion_999');
      expect(fusion.assessmentState, 'EVIDENCE_CONSISTENT');
      expect(fusion.overallConfidence, 0.94);
      expect(fusion.explanation['summary'], contains('Customer photo matches'));
    });

    test('MerchantDecision models and JSON mapping', () {
      final create = MerchantDecisionCreate(
        decision: 'REFUND_APPROVED',
        notes: 'Verified damage and receipts match.',
        actionTaken: 'FULL_REFUND',
      );
      final map = create.toJson();
      expect(map['decision'], 'REFUND_APPROVED');
      expect(map['notes'], 'Verified damage and receipts match.');
      expect(map['action_taken'], 'FULL_REFUND');

      final model = MerchantDecisionModel.fromJson({
        'id': 'dec_001',
        'verification_session_id': 'sess_12345',
        'merchant_id': 'merch_01',
        'decision': 'REFUND_APPROVED',
        'notes': 'All checks passed',
        'decided_at': '2026-09-08T11:00:00Z',
      });
      expect(model.id, 'dec_001');
      expect(model.decision, 'REFUND_APPROVED');
      expect(model.notes, 'All checks passed');
    });

    test('Dashboard verification list and 13-facet detail model', () {
      final list = DashboardVerificationListModel.fromJson(MockData.dashboardListJson);
      expect(list.items.length, 2);
      expect(list.total, 2);
      expect(list.items[0].orderId, 'ORD-9001');
      expect(list.items[0].assessmentState, 'EVIDENCE_CONSISTENT');
      expect(list.items[1].orderId, 'ORD-9002');
      expect(list.items[1].latestDecision, 'REFUND_REJECTED');

      final detail = VerificationDetailDashboardModel.fromJson(MockData.investigationDetailJson);
      expect(detail.orderId, 'ORD-9001');
      expect(detail.status, 'IN_PROGRESS');
      expect(detail.evidenceItems.length, 1);
      expect(detail.signalItems.length, 1);
      expect(detail.fusionResult?.assessmentState, 'EVIDENCE_CONSISTENT');
      expect(detail.timeline.length, 1);
    });
  });
}

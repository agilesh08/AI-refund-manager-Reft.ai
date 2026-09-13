import 'package:flutter/foundation.dart';
import '../core/network/api_exception.dart';
import '../models/customer_verification.dart';
import '../models/evidence_models.dart';
import '../models/fusion_models.dart';
import '../models/workflow_step.dart';
import '../services/customer_verification_service.dart';

class CustomerFlowProvider extends ChangeNotifier {
  final CustomerVerificationService _service;

  String? _token;
  CustomerVerificationResponse? _overview;
  CustomerWorkflowResponse? _workflow;
  int _currentStepIndex = 0;
  final Map<String, EvidenceResponseModel> _submittedEvidence = {};
  List<CustomerEvidenceRequestModel> _adaptiveRequests = [];
  CustomerFusionModel? _fusion;

  bool _isLoading = false;
  bool _isSubmitting = false;
  bool _isTokenInvalid = false;
  String? _errorMessage;

  CustomerFlowProvider({CustomerVerificationService? service})
      : _service = service ?? CustomerVerificationService();

  String? get token => _token;
  CustomerVerificationResponse? get overview => _overview;
  CustomerWorkflowResponse? get workflow => _workflow;
  int get currentStepIndex => _currentStepIndex;
  List<WorkflowStepItem> get steps => _workflow?.steps ?? [];
  WorkflowStepItem? get currentStep =>
      (steps.isNotEmpty && _currentStepIndex < steps.length)
          ? steps[_currentStepIndex]
          : null;
  Map<String, EvidenceResponseModel> get submittedEvidence =>
      _submittedEvidence;
  List<CustomerEvidenceRequestModel> get adaptiveRequests => _adaptiveRequests;
  CustomerFusionModel? get fusion => _fusion;
  bool get isLoading => _isLoading;
  bool get isSubmitting => _isSubmitting;
  bool get isTokenInvalid => _isTokenInvalid;
  String? get errorMessage => _errorMessage;

  bool get hasPendingAdaptiveRequests =>
      _adaptiveRequests.any((r) => r.isPending);

  Future<void> loadSession(String rawToken) async {
    _token = rawToken;
    _isLoading = true;
    _isTokenInvalid = false;
    _errorMessage = null;
    notifyListeners();

    try {
      _overview = await _service.getOverview(rawToken);
      _workflow = await _service.getWorkflow(rawToken);

      // Pre-load any previously submitted evidence
      final existingEvidence = await _service.listEvidence(rawToken);
      for (final ev in existingEvidence) {
        if (ev.workflowStepKey != null) {
          _submittedEvidence[ev.workflowStepKey!] = ev;
        }
      }

      await checkAdaptiveRequests();
      _isLoading = false;
      notifyListeners();
    } on ApiException catch (e) {
      _isLoading = false;
      if (e.isNotFound || e.isGone) {
        _isTokenInvalid = true;
      }
      _errorMessage = e.userMessage;
      notifyListeners();
    } catch (e) {
      _isLoading = false;
      _errorMessage = e.toString();
      notifyListeners();
    }
  }

  Future<bool> startSession() async {
    if (_token == null) return false;
    _isSubmitting = true;
    _errorMessage = null;
    notifyListeners();

    try {
      await _service.startVerification(_token!);
      _workflow ??= await _service.getWorkflow(_token!);
      _isSubmitting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : e.toString();
      _isSubmitting = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> submitStepEvidence({
    required String stepKey,
    required String stepType,
    String? textContent,
    Uint8List? imageBytes,
    String? filename,
    List<Uint8List>? additionalImages,
    List<String>? additionalFilenames,
  }) async {
    if (_token == null) return false;
    _isSubmitting = true;
    _errorMessage = null;
    notifyListeners();

    try {
      dynamic ev;
      if (stepType == 'PAYMENT') {
        // Must NEVER call submitTextEvidence for a PAYMENT step
        ev = await _service.submitPaymentProof(
          token: _token!,
          stepKey: stepKey,
          fileBytes: imageBytes,
          filename: filename,
        );
      } else if (imageBytes != null ||
          (additionalImages != null && additionalImages.isNotEmpty)) {
        if (imageBytes != null) {
          ev = await _service.uploadImageEvidence(
            token: _token!,
            fileBytes: imageBytes,
            filename: filename ?? 'evidence_$stepKey.jpg',
            workflowStepKey: stepKey,
          );
        }
        if (additionalImages != null) {
          for (int i = 0; i < additionalImages.length; i++) {
            final extraBytes = additionalImages[i];
            final extraName = (additionalFilenames != null &&
                    additionalFilenames.length > i)
                ? additionalFilenames[i]
                : 'evidence_${stepKey}_${i + 2}.jpg';
            ev = await _service.uploadImageEvidence(
              token: _token!,
              fileBytes: extraBytes,
              filename: extraName,
              workflowStepKey: stepKey,
            );
          }
        }
      } else {
        ev = await _service.submitTextEvidence(
          token: _token!,
          textContent: textContent ?? '',
          workflowStepKey: stepKey,
        );
      }

      _submittedEvidence[stepKey] = ev;
      _isSubmitting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : e.toString();
      _isSubmitting = false;
      notifyListeners();
      return false;
    }
  }

  Future<bool> submitPaymentProof({
    required String stepKey,
    String? payeeAccount,
    String? payerAccount,
    String? transactionId,
    double? amount,
    String? currency,
    String? paymentStatus,
    String? paymentMethod,
    Uint8List? fileBytes,
    String? filename,
  }) async {
    if (_token == null) return false;
    _isSubmitting = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final res = await _service.submitPaymentProof(
        token: _token!,
        stepKey: stepKey,
        payeeAccount: payeeAccount,
        payerAccount: payerAccount,
        transactionId: transactionId,
        amount: amount,
        currency: currency,
        paymentStatus: paymentStatus,
        paymentMethod: paymentMethod,
        fileBytes: fileBytes,
        filename: filename,
      );
      final evId = res['evidence_id']?.toString() ?? 'payment-$stepKey';
      _submittedEvidence[stepKey] = EvidenceResponseModel(
        id: evId,
        verificationSessionId: _overview?.verificationId ?? '',
        evidenceType: 'PAYMENT',
        mimeType: fileBytes != null ? 'image/jpeg' : 'application/json',
        workflowStepKey: stepKey,
        createdAt: DateTime.now(),
      );
      _isSubmitting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : e.toString();
      _isSubmitting = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> checkAdaptiveRequests() async {
    if (_token == null) return;
    try {
      _adaptiveRequests = await _service.listEvidenceRequests(_token!);
      notifyListeners();
    } catch (_) {}
  }

  Future<bool> fulfillAdaptiveRequest({
    required String requestId,
    Uint8List? imageBytes,
    String? filename,
    String? textContent,
    String? selectedOption,
  }) async {
    if (_token == null) return false;
    _isSubmitting = true;
    _errorMessage = null;
    notifyListeners();

    try {
      await _service.fulfillEvidenceRequest(
        token: _token!,
        requestId: requestId,
        fileBytes: imageBytes,
        filename: filename,
        textContent: textContent,
        selectedOption: selectedOption,
      );
      await checkAdaptiveRequests();
      _isSubmitting = false;
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e.toString();
      _isSubmitting = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> loadFusionAssessment() async {
    if (_token == null) return;
    try {
      _fusion = await _service.getFusion(_token!);
      notifyListeners();
    } catch (_) {}
  }

  Future<bool> triggerLiveAnalysis() async {
    if (_token == null) return false;
    _isLoading = true;
    notifyListeners();

    try {
      final res = await _service.triggerAnalysis(_token!);
      final status = res['status']?.toString();
      await checkAdaptiveRequests();
      _isLoading = false;
      notifyListeners();
      return status == 'FOLLOWUP_REQUIRED' || hasPendingAdaptiveRequests;
    } catch (e) {
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  Future<void> finalizeCompletion() async {
    if (_token == null) return;
    try {
      await _service.completeSession(_token!);
      _overview = await _service.getOverview(_token!);
      notifyListeners();
    } catch (_) {}
  }

  void nextStep() {
    if (steps.isNotEmpty && _currentStepIndex < steps.length - 1) {
      _currentStepIndex++;
      notifyListeners();
    }
  }

  void previousStep() {
    if (_currentStepIndex > 0) {
      _currentStepIndex--;
      notifyListeners();
    }
  }

  void goToStep(int index) {
    if (index >= 0 && index < steps.length) {
      _currentStepIndex = index;
      notifyListeners();
    }
  }
}

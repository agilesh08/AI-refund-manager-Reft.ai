import 'package:flutter/foundation.dart';
import '../core/network/api_exception.dart';
import '../models/merchant_decision_models.dart';
import '../models/report_models.dart';
import '../services/merchant_service.dart';

class MerchantDashboardProvider extends ChangeNotifier {
  final MerchantService _service;

  List<DashboardVerificationItemModel> _items = [];
  int _total = 0;
  int _currentPage = 1;
  final int _pageSize = 20;

  String _statusFilter = 'ALL';
  String _assessmentFilter = 'ALL';
  String _searchQuery = '';

  bool _isLoadingList = false;
  bool _isLoadingDetail = false;
  bool _isSubmittingDecision = false;
  String? _errorMessage;

  VerificationDetailDashboardModel? _selectedVerification;
  ExplainableVerificationReportModel? _selectedReport;
  List<TimelineItemModel> _selectedTimeline = [];

  MerchantDashboardProvider({MerchantService? service})
      : _service = service ?? MerchantService();

  List<DashboardVerificationItemModel> get items => _items;
  int get total => _total;
  int get currentPage => _currentPage;
  int get pageSize => _pageSize;
  String get statusFilter => _statusFilter;
  String get assessmentFilter => _assessmentFilter;
  String get searchQuery => _searchQuery;

  bool get isLoadingList => _isLoadingList;
  bool get isLoadingDetail => _isLoadingDetail;
  bool get isSubmittingDecision => _isSubmittingDecision;
  String? get errorMessage => _errorMessage;

  VerificationDetailDashboardModel? get selectedVerification =>
      _selectedVerification;
  ExplainableVerificationReportModel? get selectedReport => _selectedReport;
  List<TimelineItemModel> get selectedTimeline => _selectedTimeline;

  // Stats calculation
  int get totalCount => _total;
  int get consistentCount => _items
      .where((i) =>
          (i.assessmentState ?? '').toUpperCase() == 'EVIDENCE_CONSISTENT')
      .length;
  int get reviewRequiredCount => _items
      .where((i) =>
          (i.assessmentState ?? '').toUpperCase() == 'REVIEW_REQUIRED')
      .length;
  int get inconsistentCount => _items
      .where((i) =>
          (i.assessmentState ?? '').toUpperCase() == 'INCONSISTENCY_DETECTED')
      .length;
  int get pendingDecisionCount =>
      _items.where((i) => i.latestDecision == null).length;

  DateTime? _lastFetchTime;

  Future<void> loadVerifications({bool refresh = false}) async {
    if (_isLoadingList) return;

    final now = DateTime.now();
    if (!refresh &&
        _lastFetchTime != null &&
        now.difference(_lastFetchTime!).inMilliseconds < 1500) {
      return;
    }
    _lastFetchTime = now;

    if (refresh) {
      _currentPage = 1;
    }
    _isLoadingList = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final res = await _service.listVerifications(
        status: _statusFilter,
        assessmentState: _assessmentFilter,
        search: _searchQuery,
        page: _currentPage,
        pageSize: _pageSize,
      );
      _items = res.items;
      _total = res.total;
      _isLoadingList = false;
      notifyListeners();
    } catch (e) {
      _isLoadingList = false;
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to load verifications.';
      notifyListeners();
    }
  }

  void setSearch(String query) {
    _searchQuery = query;
    _currentPage = 1;
    loadVerifications();
  }

  void setStatusFilter(String status) {
    _statusFilter = status;
    _currentPage = 1;
    loadVerifications();
  }

  void setAssessmentFilter(String state) {
    _assessmentFilter = state;
    _currentPage = 1;
    loadVerifications();
  }

  Future<void> loadInvestigationDetail(String verificationId) async {
    _isLoadingDetail = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _selectedVerification =
          await _service.getInvestigationDetail(verificationId);
      _isLoadingDetail = false;
      notifyListeners();
    } catch (e) {
      _isLoadingDetail = false;
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to load investigation details.';
      notifyListeners();
    }
  }

  Future<void> loadReport(String verificationId) async {
    _isLoadingDetail = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _selectedReport = await _service.getReport(verificationId);
      _isLoadingDetail = false;
      notifyListeners();
    } catch (e) {
      _isLoadingDetail = false;
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to load verification report.';
      notifyListeners();
    }
  }

  Future<void> loadTimeline(String verificationId) async {
    _isLoadingDetail = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _selectedTimeline = await _service.getTimeline(verificationId);
      _isLoadingDetail = false;
      notifyListeners();
    } catch (e) {
      _isLoadingDetail = false;
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to load audit timeline.';
      notifyListeners();
    }
  }

  Future<bool> submitDecision(
      String verificationId, MerchantDecisionCreate decision) async {
    _isSubmittingDecision = true;
    _errorMessage = null;
    notifyListeners();

    try {
      await _service.recordDecision(
        verificationId: verificationId,
        decision: decision,
      );

      // Refresh detail and list
      if (_selectedVerification != null &&
          _selectedVerification!.verificationId == verificationId) {
        await loadInvestigationDetail(verificationId);
      }
      await loadVerifications(refresh: true);

      _isSubmittingDecision = false;
      notifyListeners();
      return true;
    } catch (e) {
      _isSubmittingDecision = false;
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to record merchant decision.';
      notifyListeners();
      return false;
    }
  }

  Future<bool> holdVerification(
    String verificationId, {
    int? durationSeconds,
    String? reason,
  }) async {
    try {
      await _service.holdVerification(
        verificationId: verificationId,
        durationSeconds: durationSeconds,
        reason: reason,
      );
      if (_selectedVerification != null &&
          _selectedVerification!.verificationId == verificationId) {
        await loadInvestigationDetail(verificationId);
      }
      await loadVerifications(refresh: true);
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to hold verification.';
      notifyListeners();
      return false;
    }
  }

  Future<bool> resumeVerification(String verificationId) async {
    try {
      await _service.resumeVerification(verificationId);
      if (_selectedVerification != null &&
          _selectedVerification!.verificationId == verificationId) {
        await loadInvestigationDetail(verificationId);
      }
      await loadVerifications(refresh: true);
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to resume verification.';
      notifyListeners();
      return false;
    }
  }

  Future<bool> deleteVerification(String verificationId) async {
    try {
      await _service.deleteVerification(verificationId);
      _items.removeWhere((i) => i.verificationId == verificationId);
      _total = (_total > 0) ? _total - 1 : 0;
      if (_selectedVerification?.verificationId == verificationId) {
        _selectedVerification = null;
      }
      notifyListeners();
      return true;
    } catch (e) {
      _errorMessage = e is ApiException ? e.userMessage : 'Failed to delete verification.';
      notifyListeners();
      return false;
    }
  }
}

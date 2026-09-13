import 'package:flutter/material.dart';

/// App color palette adhering strictly to M13 Material 3 specifications.
class AppColors {
  // Brand / Theme Colors
  static const Color primary = Color(0xFF6A89A7); // Refined Slate Blue
  static const Color primaryLight = Color(0xFFBDDDFC); // Soft Ice Blue
  static const Color secondary = Color(0xFF88BDF2); // Sky Blue Accent
  static const Color darkNeutral = Color(0xFF384959); // Deep Slate Navy Text

  // Surfaces & Backgrounds
  static const Color background = Color(0xFFF6F9FC); // Modern clean light blue-grey
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceVariant = Color(0xFFF1F5F9);
  static const Color border = Color(0xFFE2E8F0);
  static const Color borderSubtle = Color(0xFFEDF2F7);
  static const Color textSecondary = Color(0xFF64748B);
  static const Color textMuted = Color(0xFF94A3B8);

  // Machine Assessment State Colors (Refined Modern Semantic)
  static const Color assessmentConsistent = Color(0xFF059669); // Modern Emerald Green
  static const Color assessmentConsistentBg = Color(0xFFECFDF5);
  static const Color assessmentReviewRequired = Color(0xFFD97706); // Amber
  static const Color assessmentReviewRequiredBg = Color(0xFFFFFBEB);
  static const Color assessmentInconsistent = Color(0xFFDC2626); // Crimson Red
  static const Color assessmentInconsistentBg = Color(0xFFFEF2F2);

  // Merchant Decision Colors (Strictly separate from Machine Assessment)
  static const Color decisionApproved = Color(0xFF047857); // Deep Emerald
  static const Color decisionApprovedBg = Color(0xFFECFDF5);
  static const Color decisionRejected = Color(0xFFB91C1C); // Deep Crimson
  static const Color decisionRejectedBg = Color(0xFFFEF2F2);
  static const Color decisionManualReview = Color(0xFF0369A1); // Deep Ocean Blue
  static const Color decisionManualReviewBg = Color(0xFFF0F9FF);

  // Session Status Colors
  static const Color statusCreated = Color(0xFF64748B);
  static const Color statusInProgress = Color(0xFF0284C7);
  static const Color statusAnalyzed = Color(0xFF7C3AED);
  static const Color statusCompleted = Color(0xFF059669);
  static const Color statusExpired = Color(0xFF64748B);
  static const Color statusCancelled = Color(0xFFDC2626);
  static const Color statusHeld = Color(0xFFE65100); // Amber/Orange for On Hold
  static const Color statusHeldBg = Color(0xFFFFF3E0);

  // Color helpers based on string codes
  static Color forAssessment(String? state) {
    switch (state?.toUpperCase()) {
      case 'EVIDENCE_CONSISTENT':
        return assessmentConsistent;
      case 'REVIEW_REQUIRED':
        return assessmentReviewRequired;
      case 'INCONSISTENCY_DETECTED':
        return assessmentInconsistent;
      default:
        return textSecondary;
    }
  }

  static Color forAssessmentBg(String? state) {
    switch (state?.toUpperCase()) {
      case 'EVIDENCE_CONSISTENT':
        return assessmentConsistentBg;
      case 'REVIEW_REQUIRED':
        return assessmentReviewRequiredBg;
      case 'INCONSISTENCY_DETECTED':
        return assessmentInconsistentBg;
      default:
        return surfaceVariant;
    }
  }

  static Color forDecision(String? decision) {
    switch (decision?.toUpperCase()) {
      case 'HOLD':
      case 'HELD':
        return statusHeld;
      case 'REFUND_APPROVED':
      case 'APPROVED':
        return decisionApproved;
      case 'REFUND_REJECTED':
      case 'REJECTED':
        return decisionRejected;
      case 'MANUAL_REVIEW':
        return decisionManualReview;
      default:
        return textSecondary;
    }
  }

  static Color forDecisionBg(String? decision) {
    switch (decision?.toUpperCase()) {
      case 'HOLD':
      case 'HELD':
        return statusHeldBg;
      case 'REFUND_APPROVED':
      case 'APPROVED':
        return decisionApprovedBg;
      case 'REFUND_REJECTED':
      case 'REJECTED':
        return decisionRejectedBg;
      case 'MANUAL_REVIEW':
        return decisionManualReviewBg;
      default:
        return surfaceVariant;
    }
  }

  static Color forStatus(String? status) {
    switch (status?.toUpperCase()) {
      case 'CREATED':
        return statusCreated;
      case 'IN_PROGRESS':
        return statusInProgress;
      case 'READY_FOR_ANALYSIS':
      case 'ANALYZED':
        return statusAnalyzed;
      case 'COMPLETED':
        return statusCompleted;
      case 'EXPIRED':
        return statusExpired;
      case 'CANCELLED':
        return statusCancelled;
      case 'HELD':
        return statusHeld;
      default:
        return textSecondary;
    }
  }
}

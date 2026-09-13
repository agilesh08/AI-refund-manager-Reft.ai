import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../../core/constants/app_colors.dart';

/// Screen displayed when verification token is expired, invalid, or cancelled.
class InvalidTokenScreen extends StatelessWidget {
  final String? errorMessage;

  const InvalidTokenScreen({super.key, this.errorMessage});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Refund Verification'),
        automaticallyImplyLeading: false,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(20),
                decoration: const BoxDecoration(
                  color: AppColors.assessmentReviewRequiredBg,
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.link_off_rounded,
                  size: 56,
                  color: AppColors.assessmentReviewRequired,
                ),
              ),
              const SizedBox(height: 24),
              const Text(
                'Verification Link Expired or Invalid',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  color: AppColors.darkNeutral,
                ),
              ),
              const SizedBox(height: 12),
              Text(
                errorMessage ??
                    'This verification session has expired or is no longer accessible. Please contact your merchant support to request a new verification link.',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 14,
                  color: AppColors.textSecondary,
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 32),
              ElevatedButton.icon(
                onPressed: () => context.go('/'),
                icon: const Icon(Icons.home_rounded, size: 18),
                label: const Text('Return to Home'),
                style: ElevatedButton.styleFrom(
                  minimumSize: const Size(200, 48),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

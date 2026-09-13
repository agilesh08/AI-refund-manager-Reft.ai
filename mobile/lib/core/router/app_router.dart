import 'package:go_router/go_router.dart';
import '../../features/auth/login_screen.dart';
import '../../features/customer/customer_completion_screen.dart';
import '../../features/customer/invalid_token_screen.dart';
import '../../features/customer/reviewing_screen.dart';
import '../../features/customer/session_overview_screen.dart';
import '../../features/customer/workflow_runner_screen.dart';
import '../../features/gateway/gateway_screen.dart';
import '../../features/merchant/create_verification_screen.dart';
import '../../features/merchant/dashboard_screen.dart';
import '../../features/merchant/investigation_screen.dart';
import '../../features/merchant/customer_response_screen.dart';
import '../../features/merchant/report_screen.dart';
import '../../features/merchant/timeline_screen.dart';
import '../../features/merchant/verification_created_screen.dart';
import '../../features/merchant/workflow_builder_screen.dart';
import '../../features/merchant/settings/merchant_settings_screen.dart';
import '../../features/merchant/settings/product_list_screen.dart';
import '../../features/merchant/settings/product_reference_evidence_screen.dart';

/// Centralized declarative router configuration supporting secure deep links and app flows.
class AppRouter {
  static final GoRouter router = GoRouter(
    initialLocation: '/',
    errorBuilder: (context, state) => const GatewayScreen(),
    routes: [


      // First-launch Role Gateway
      GoRoute(
        path: '/',
        builder: (context, state) => const GatewayScreen(),
      ),

      // Merchant Authentication
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),

      // Merchant Dashboard
      GoRoute(
        path: '/dashboard',
        builder: (context, state) => const DashboardScreen(),
      ),

      // Merchant Settings Hub
      GoRoute(
        path: '/settings',
        builder: (context, state) => const MerchantSettingsScreen(),
      ),

      // Merchant Products List
      GoRoute(
        path: '/settings/products',
        builder: (context, state) => const ProductListScreen(),
      ),

      // Merchant Product Reference Evidence
      GoRoute(
        path: '/settings/products/:id/references',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          final product = state.extra as Map<String, dynamic>?;
          return ProductReferenceEvidenceScreen(
            productId: id,
            initialProduct: product,
          );
        },
      ),

      // Merchant Create Verification
      GoRoute(
        path: '/create-verification',
        builder: (context, state) => const CreateVerificationScreen(),
      ),

      // Merchant Verification Created Success
      GoRoute(
        path: '/verification-created',
        builder: (context, state) {
          final session = state.extra as Map<String, dynamic>? ?? {};
          return VerificationCreatedScreen(session: session);
        },
      ),

      // Merchant Workflow Builder
      GoRoute(
        path: '/workflows',
        builder: (context, state) => const WorkflowBuilderScreen(),
      ),

      // Merchant 13-Facet Investigation View
      GoRoute(
        path: '/investigation/:id',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          return InvestigationScreen(verificationId: id);
        },
      ),

      // Merchant Dedicated Customer Response Journey View
      GoRoute(
        path: '/investigation/:id/customer-response',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          return CustomerResponseScreen(verificationId: id);
        },
      ),

      // Merchant 9-Section Explainable Final Report
      GoRoute(
        path: '/report/:id',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          return ReportScreen(verificationId: id);
        },
      ),
      GoRoute(
        path: '/investigation/:id/report',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          return ReportScreen(verificationId: id);
        },
      ),

      // Merchant Audit Event Timeline
      GoRoute(
        path: '/timeline/:id',
        builder: (context, state) {
          final id = state.pathParameters['id'] ?? '';
          return TimelineScreen(verificationId: id);
        },
      ),

      // Public Customer Secure Deep Link Route
      GoRoute(
        path: '/verify/:token',
        builder: (context, state) {
          final token = state.pathParameters['token'] ?? '';
          return SessionOverviewScreen(token: token);
        },
        routes: [
          GoRoute(
            path: 'workflow',
            builder: (context, state) {
              final token = state.pathParameters['token'] ?? '';
              return WorkflowRunnerScreen(token: token);
            },
          ),
          GoRoute(
            path: 'reviewing',
            builder: (context, state) {
              final token = state.pathParameters['token'] ?? '';
              return ReviewingScreen(token: token);
            },
          ),
          GoRoute(
            path: 'completed',
            builder: (context, state) {
              final token = state.pathParameters['token'] ?? '';
              return CustomerCompletionScreen(token: token);
            },
          ),
          GoRoute(
            path: 'invalid',
            builder: (context, state) => const InvalidTokenScreen(),
          ),
        ],
      ),
    ],
  );
}

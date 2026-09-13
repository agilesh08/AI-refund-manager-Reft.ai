import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'core/constants/api_endpoints.dart';
import 'core/router/app_router.dart';
import 'core/storage/token_storage.dart';
import 'core/theme/app_theme.dart';
import 'state/auth_provider.dart';
import 'state/customer_flow_provider.dart';
import 'state/merchant_dashboard_provider.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load saved base URL if previously customized by user
  final tokenStorage = TokenStorage();
  await tokenStorage.init();
  final savedUrl = await tokenStorage.getSavedBaseUrl();
  if (savedUrl != null && savedUrl.isNotEmpty) {
    ApiEndpoints.setBaseUrl(savedUrl);
  }

  runApp(const RefundVerificationApp());
}

class RefundVerificationApp extends StatelessWidget {
  const RefundVerificationApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()..checkAuthStatus()),
        ChangeNotifierProvider(create: (_) => CustomerFlowProvider()),
        ChangeNotifierProvider(create: (_) => MerchantDashboardProvider()),
      ],
      child: MaterialApp.router(
        title: 'Reft.AI',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.lightTheme,
        routerConfig: AppRouter.router,
      ),
    );
  }
}

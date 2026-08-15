import { AppErrorBoundary } from "./components/AppErrorBoundary";
import { HomePage } from "./features/home/HomePage";

export function App() {
  return (
    <AppErrorBoundary>
      <HomePage />
    </AppErrorBoundary>
  );
}

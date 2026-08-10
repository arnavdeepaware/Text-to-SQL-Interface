import { render, screen } from "@testing-library/react";

import { App } from "./App";

test("renders the application shell and backend health", async () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: /read-only query client foundation/i })).toBeVisible();
  expect(await screen.findByText(/api is ready/i)).toBeVisible();
  expect(screen.getByText("0.1.0")).toBeVisible();
});

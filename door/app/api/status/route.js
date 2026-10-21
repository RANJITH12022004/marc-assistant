import { piFetch } from "../../../lib/pi";

export const dynamic = "force-dynamic";

export async function GET() {
  return piFetch("/status");
}

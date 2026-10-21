import { piFetch } from "../../../lib/pi";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(request) {
  let body = {};
  try {
    body = await request.json();
  } catch {
    body = {};
  }
  return piFetch("/confirm", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

import { relay } from "../../../lib/relay";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(request) {
  return relay(request, "/utterance");
}

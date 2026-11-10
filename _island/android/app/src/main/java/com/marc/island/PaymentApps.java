package com.marc.island;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

/** Bank and UPI packages. Marc steps aside while one of these is in front. */
final class PaymentApps {
    private PaymentApps() {}

    static boolean isPayment(String packageName) {
        if (packageName == null || packageName.isEmpty()) {
            return false;
        }
        switch (packageName) {
            case "com.google.android.apps.nbu.paisa.user":
            case "com.phonepe.app":
            case "net.one97.paytm":
            case "in.org.npci.upiapp":
            case "com.dreamplug.androidapp":
            case "in.amazon.mShop.android.shopping":
            case "com.amazon.mShop.android.shopping":
            case "com.csam.icici.bank.imobile":
            case "com.snapwork.hdfc":
            case "com.sbi.lotusintouch":
            case "com.sbi.SBIFreedomPlus":
            case "com.axis.mobile":
            case "com.msf.kbank.mobile":
            case "com.hdfcbank.payzapp":
            case "com.mobikwik_new":
            case "com.freecharge.android":
            case "com.myairtelapp":
                return true;
            default:
                return false;
        }
    }

    static boolean named(String name) {
        String folded = name == null ? "" : name.trim().toLowerCase(Locale.US);
        if (folded.isEmpty()) {
            return false;
        }
        return folded.contains("phonepe")
                || folded.contains("phone pe")
                || folded.contains("gpay")
                || folded.contains("google pay")
                || folded.contains("paytm")
                || folded.contains("bhim")
                || folded.equals("cred")
                || folded.contains("amazon pay")
                || folded.contains("hdfc")
                || folded.contains("icici")
                || folded.equals("sbi")
                || folded.contains("axis bank")
                || folded.equals("axis")
                || folded.contains("kotak")
                || folded.contains("payzapp")
                || folded.contains("mobikwik")
                || folded.contains("freecharge")
                || folded.contains("airtel");
    }

    static boolean opens(JSONArray steps) {
        if (steps == null) {
            return false;
        }
        for (int i = 0; i < steps.length(); i++) {
            JSONObject step = steps.optJSONObject(i);
            if (step == null || !"open_app".equals(step.optString("tool"))) {
                continue;
            }
            JSONObject args = step.optJSONObject("args");
            String name = args == null ? "" : args.optString("name", args.optString("app"));
            if (named(name)) {
                return true;
            }
        }
        return false;
    }
}

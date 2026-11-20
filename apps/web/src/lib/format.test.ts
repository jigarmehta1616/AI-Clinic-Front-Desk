import { describe, expect, it } from "vitest";

import { addDays, addMonths, dayIn, formatDate, formatMoney, formatPhone, formatTime, minutesUntil } from "./format";

const IST = "Asia/Kolkata";

describe("clinic time-zone formatting", () => {
  it("formats UTC instants in IST", () => {
    expect(formatTime("2026-11-24T04:45:00Z", IST)).toBe("10:15 AM");
    expect(formatTime("2026-11-24T13:30:00Z", IST)).toBe("7:00 PM");
    expect(formatDate("2026-11-24T04:45:00Z", IST)).toBe("Tue, 24 Nov");
  });

  it("uses the clinic's local date around midnight", () => {
    // 19:00 UTC = 00:30 IST next day
    expect(dayIn(IST, new Date("2026-11-23T19:00:00Z"))).toBe("2026-11-24");
    expect(dayIn(IST, new Date("2026-11-23T18:00:00Z"))).toBe("2026-11-23");
  });

  it("does date arithmetic on plain days", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(formatDate("2026-11-24", IST)).toBe("Tue, 24 Nov");
  });

  it("formats money and phones for India", () => {
    expect(formatMoney(60000)).toBe("₹600");
    expect(formatMoney(12345600)).toBe("₹1,23,456");
    expect(formatPhone("+919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("+14155550100")).toBe("+14155550100");
  });

  it("never returns negative minutes", () => {
    const now = new Date("2026-11-24T10:00:00Z");
    expect(minutesUntil("2026-11-24T10:20:00Z", now)).toBe(20);
    expect(minutesUntil("2026-11-24T09:00:00Z", now)).toBe(0);
  });
});

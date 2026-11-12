"""All texts the API writes for people: warnings and advice, in English and Uzbek."""
from __future__ import annotations

from .climate import BASELINE, PROJECTION_YEAR

LANGS = ("en", "uz")

WARN = {
    "en": {
        "disabled": "{name} is switched off. Analysis that needs it was skipped.",
        "power_failed": "NASA POWER did not respond and there is no saved data near this point. Climate, crop and rotation analysis was skipped. Try a preset location.",
        "power_fallback": "NASA POWER did not respond. Showing saved data of a point {km} km away. Numbers do not exactly match this place.",
        "power_monthly": "NASA POWER daily data did not arrive, so monthly data is used. Heat days, frost dates and dry spells are approximate or missing.",
        "not_land": "This point looks like open water or ice: NASA has no soil data here. The crop results below have no practical meaning.",
        "layer_down": "{name} did not respond. Its map layers are hidden.",
        "soil_down": "{name} did not respond. Soil is set to '{soil}'. Choose your soil type in the field passport for a better result.",
        "forecast_down": "{name} did not respond. The weekly outlook uses what usually happens on these dates (NASA data, 2011-2025) instead of a forecast.",
        "json_failed": "{name} did not respond and was left out.",
        "conflict": "In '{name}' the seasons of {a} and {b} overlap by {days} days. This rotation cannot be grown as written.",
    },
    "uz": {
        "disabled": "{name} o'chirilgan. Unga tayanadigan tahlil o'tkazib yuborildi.",
        "power_failed": "NASA POWER javob bermadi va bu joy yaqinida saqlangan ma'lumot yo'q. Iqlim, ekin va rotatsiya tahlili o'tkazib yuborildi. Tayyor joylardan birini tanlang.",
        "power_fallback": "NASA POWER javob bermadi. {km} km uzoqlikdagi saqlangan nuqta ma'lumoti ko'rsatilmoqda. Raqamlar aynan shu joyga mos emas.",
        "power_monthly": "NASA POWER kunlik ma'lumoti kelmadi, shuning uchun oylik ma'lumot ishlatildi. Issiq kunlar, sovuq sanalari va qurg'oqchil davrlar taxminiy yoki yo'q.",
        "not_land": "Bu nuqta suv yoki muzlikka o'xshaydi: NASA'da bu yer uchun tuproq ma'lumoti yo'q. Quyidagi ekin natijalari amaliy ma'noga ega emas.",
        "layer_down": "{name} javob bermadi. Uning xarita qatlamlari yashirildi.",
        "soil_down": "{name} javob bermadi. Tuproq '{soil}' deb olindi. Aniqroq natija uchun dala pasportida tuproq turini tanlang.",
        "forecast_down": "{name} javob bermadi. Haftalik ko'rsatkich prognoz o'rniga shu sanalarda odatda nima bo'lishiga (NASA ma'lumoti, 2011-2025) tayanadi.",
        "json_failed": "{name} javob bermadi va tahlilga qo'shilmadi.",
        "conflict": "'{name}' rotatsiyasida {a} va {b} mavsumlari {days} kun ustma-ust tushadi. Bu rotatsiyani shu ko'rinishda ekib bo'lmaydi.",
    },
}

DISCLAIMER = {
    "en": "Climate numbers come from NASA POWER on a grid of about 50 km, so nearby fields get the same climate. Water need is computed for regional weather; over irrigated land the real value is usually somewhat lower (FAO-56, Annex 6), so use the numbers to compare crops, rotations and periods. Crop thresholds, soil index and income are transparent rules, not measurements or a yield forecast.",
    "uz": "Iqlim raqamlari NASA POWER'dan, taxminan 50 km to'rda olingan, shuning uchun yaqin dalalar bir xil iqlim oladi. Suv ehtiyoji hududiy ob-havo uchun hisoblangan; sug'oriladigan yer ustida haqiqiy qiymat odatda biroz past bo'ladi (FAO-56, 6-ilova), shu sababli raqamlarni ekinlar, rotatsiyalar va davrlarni solishtirish uchun ishlating. Ekin chegaralari, tuproq indeksi va daromad ochiq qoidalar, o'lchov yoki hosil prognozi emas.",
}

_ADVICE = {
    "en": {
        "best_is_current": "For your priorities, your current rotation '{cur}' is already the best of the {n} compared (score {score} of 100).",
        "best": "For your priorities, '{best}' scores highest: {score} of 100 against {cur_score} for your current '{cur}'.",
        "best_water_less": "It needs about {m3} m3/ha less water per year ({pct}% less).",
        "best_water_more": "It needs about {m3} m3/ha more water per year ({pct}% more).",
        "best_income": "Estimated income changes by {usd:+.0f} USD/ha per year.",
        "best_soil": "Soil health index: {a} against {b}.",
        "stable": "It came first in {wins} of {n} weather years (2011-2025), so the choice is robust.",
        "unstable": "It came first in only {wins} of {n} weather years: '{runner}' is close. Treat the two as equal and decide by what matters most to you.",
        "warming": "Average temperature here is {d:+.1f} °C compared with {b0}-{b1} ({trend:+.2f} °C per decade{sig}). If the trend continues, about {proj:.1f} °C by {py} (likely range {lo:.1f} to {hi:.1f}).",
        "rain": "Yearly precipitation changed by {pct:+.0f}% ({base:.0f} to {recent:.0f} mm). Year-to-year differences are large, so this alone is not a reliable trend.",
        "rain_sig": "Yearly precipitation changed by {pct:+.0f}% ({base:.0f} to {recent:.0f} mm), a statistically significant trend.",
        "demand": "The air now takes {d:+.0f} mm more water per year from fields (reference evapotranspiration {base:.0f} to {recent:.0f} mm).",
        "hot_days": "Days hotter than 35 °C: {base:.0f} per year before, {recent:.0f} now.",
        "frost": "The last spring frost now comes around {recent} (before: {base}), and the frost-free season is {d:+.0f} days longer.",
        "frost_shorter": "The last spring frost now comes around {recent} (before: {base}), and the frost-free season is {d:.0f} days shorter.",
        "sowing": "{crop}: the suitable sowing date moved from {base} to {recent} ({d:+.0f} days).",
        "crop_stress": "{crop}: in {share:.0%} of recent years there were at least {limit} days above {thr} °C in its sensitive stage (before: {before:.0%}).",
        "now_dry": "The last 30 days brought {rain} mm of rain, drier than {pct}% of the same dates on record.",
        "now_wet": "The last 30 days brought {rain} mm of rain, wetter than {pct}% of the same dates on record.",
        "next_rain": "Forecast ({src}): next rain around {date} ({mm} mm); {week} mm expected in the next 7 days.",
        "no_rain": "Forecast ({src}): no rain of 1 mm or more in the next {n} days.",
        "usual_rain": "On these dates it usually rains within {days} days (in {prob:.0%} of years within a week).",
        "week": "{crop} is in the field now: about {mm} mm of water needed this week, {m3} m3/ha with your irrigation method.",
        "sig": ", statistically significant",
    },
    "uz": {
        "best_is_current": "Sizning ustuvorliklaringiz bo'yicha hozirgi rotatsiyangiz '{cur}' solishtirilgan {n} tadan eng yaxshisi (100 dan {score} ball).",
        "best": "Sizning ustuvorliklaringiz bo'yicha '{best}' eng yuqori ball oldi: 100 dan {score}, hozirgi '{cur}' esa {cur_score}.",
        "best_water_less": "U yiliga gektariga taxminan {m3} m3 kam suv talab qiladi ({pct}% kam).",
        "best_water_more": "U yiliga gektariga taxminan {m3} m3 ko'p suv talab qiladi ({pct}% ko'p).",
        "best_income": "Taxminiy daromad yiliga gektariga {usd:+.0f} AQSh dollariga o'zgaradi.",
        "best_soil": "Tuproq salomatligi indeksi: {a}, hozirgisida {b}.",
        "stable": "U {n} ta ob-havo yilining (2011-2025) {wins} tasida birinchi bo'ldi, ya'ni tanlov barqaror.",
        "unstable": "U {n} ta ob-havo yilining faqat {wins} tasida birinchi bo'ldi: '{runner}' unga yaqin. Ikkalasini teng deb hisoblab, o'zingiz uchun muhimiga qarab tanlang.",
        "warming": "Bu yerda o'rtacha harorat {b0}-{b1} yillarga nisbatan {d:+.1f} °C ga o'zgargan (har o'n yilda {trend:+.2f} °C{sig}). Trend davom etsa, {py} yilga borib taxminan {proj:.1f} °C (ehtimoliy oraliq {lo:.1f} dan {hi:.1f} gacha).",
        "rain": "Yillik yog'in {pct:+.0f}% ga o'zgargan ({base:.0f} dan {recent:.0f} mm ga). Yillar orasidagi farq katta, shuning uchun buning o'zi ishonchli trend emas.",
        "rain_sig": "Yillik yog'in {pct:+.0f}% ga o'zgargan ({base:.0f} dan {recent:.0f} mm ga), bu statistik jihatdan ishonchli trend.",
        "demand": "Havo dalalardan yiliga {d:+.0f} mm ko'proq suv olmoqda (etalon bug'lanish {base:.0f} dan {recent:.0f} mm ga).",
        "hot_days": "35 °C dan issiq kunlar: avval yiliga {base:.0f} ta, hozir {recent:.0f} ta.",
        "frost": "Oxirgi bahorgi sovuq hozir taxminan {recent} da (avval: {base}), sovuqsiz mavsum {d:+.0f} kunga uzaygan.",
        "frost_shorter": "Oxirgi bahorgi sovuq hozir taxminan {recent} da (avval: {base}), sovuqsiz mavsum {d:.0f} kunga qisqargan.",
        "sowing": "{crop}: qulay ekish sanasi {base} dan {recent} ga siljigan ({d:+.0f} kun).",
        "crop_stress": "{crop}: so'nggi yillarning {share:.0%} qismida nozik davrida {thr} °C dan issiq kunlar {limit} tadan oshgan (avval: {before:.0%}).",
        "now_dry": "Oxirgi 30 kunda {rain} mm yomg'ir yog'di. Bu shu sanalar tarixining {pct}% idan quruqroq.",
        "now_wet": "Oxirgi 30 kunda {rain} mm yomg'ir yog'di. Bu shu sanalar tarixining {pct}% idan seryog'inroq.",
        "next_rain": "Prognoz ({src}): keyingi yomg'ir taxminan {date} da ({mm} mm); kelgusi 7 kunda {week} mm kutilmoqda.",
        "no_rain": "Prognoz ({src}): kelgusi {n} kunda 1 mm va undan ko'p yomg'ir kutilmaydi.",
        "usual_rain": "Bu sanalarda odatda {days} kun ichida yomg'ir yog'adi (yillarning {prob:.0%} ida bir hafta ichida).",
        "week": "{crop} hozir dalada: bu hafta taxminan {mm} mm suv kerak, sizning sug'orish usulingizda gektariga {m3} m3.",
        "sig": ", statistik jihatdan ishonchli",
    },
}


_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"],
}


def day(lang: str, value: str) -> str:
    """'04-10' or '2026-04-10' -> '10 Apr' / '10-aprel'."""
    month, dom = int(value[-5:-3]), int(value[-2:])
    return f"{dom} {_MONTHS[lang][month - 1]}" if lang == "en" else f"{dom}-{_MONTHS[lang][month - 1]}"


def advice(lang: str, climate: dict, crops: list, rotations: dict, now: dict) -> list[dict]:
    t = _ADVICE[lang]
    out = []

    def add(group, severity, text):
        out.append({"group": group, "severity": severity, "text": text})

    def name(obj):
        return obj["name"].get(lang, obj["name"]["en"])

    # 1. rotation decision
    items = rotations.get("items") or []
    if items:
        best = next(it for it in items if it["id"] == rotations["best_id"])
        cur = next(it for it in items if it["is_current"])
        n = rotations["years_replayed"]
        if best["id"] == cur["id"]:
            parts = [t["best_is_current"].format(cur=name(cur), n=len(items), score=best["scores"]["total"])]
        else:
            vs = best["vs_current"]
            parts = [t["best"].format(best=name(best), score=best["scores"]["total"],
                                      cur=name(cur), cur_score=cur["scores"]["total"])]
            if vs["water_pct"] is None:
                pass  # current rotation needs no irrigation water, so a percentage has no meaning
            elif vs["water_m3_ha"] >= 100:
                parts.append(t["best_water_less"].format(m3=vs["water_m3_ha"], pct=abs(vs["water_pct"])))
            elif vs["water_m3_ha"] <= -100:
                parts.append(t["best_water_more"].format(m3=-vs["water_m3_ha"], pct=abs(vs["water_pct"])))
            parts.append(t["best_income"].format(usd=vs["income_usd_ha"]))
            parts.append(t["best_soil"].format(a=best["soil"]["index"], b=cur["soil"]["index"]))
        add("rotation", "tip", " ".join(parts))
        runner = next((it for it in items if it["id"] != best["id"] and not it["conflicts"]), None)
        if rotations["clear_winner"] or not runner:
            add("rotation", "info", t["stable"].format(wins=best["wins"], n=n))
        else:
            add("rotation", "warning", t["unstable"].format(wins=best["wins"], n=n, runner=name(runner)))

    # 2. climate shift
    s = climate["shift"]
    tm = s["t_mean"]
    if tm["delta"] is not None and abs(tm["delta"]) >= 0.3 and tm["projection"]:
        p = tm["projection"]
        add("climate", "warning" if tm["delta"] >= 1 else "info", t["warming"].format(
            d=tm["delta"], b0=BASELINE[0], b1=BASELINE[1], trend=tm["trend_per_decade"],
            sig=t["sig"] if tm["trend_significant"] else "", proj=p["value"], py=PROJECTION_YEAR,
            lo=p["low"], hi=p["high"]))
    pr = s["precip_mm"]
    if pr["delta_pct"] is not None and abs(pr["delta_pct"]) >= 5:
        key = "rain_sig" if pr["trend_significant"] else "rain"
        add("climate", "warning" if pr["delta_pct"] <= -10 else "info",
            t[key].format(pct=pr["delta_pct"], base=pr["baseline"], recent=pr["recent"]))
    et = s["et0_mm"]
    if et["delta"] is not None and et["delta"] >= 20:
        add("climate", "warning", t["demand"].format(d=et["delta"], base=et["baseline"], recent=et["recent"]))
    hd = s.get("hot_days")
    if hd and hd["delta"] is not None and hd["delta"] >= 3:
        add("climate", "warning" if hd["delta"] >= 7 else "info", t["hot_days"].format(base=hd["baseline"], recent=hd["recent"]))
    fr = climate.get("frost")
    if fr and abs(fr["frost_free_change_days"]) >= 5:
        change = fr["frost_free_change_days"]
        add("climate", "info", t["frost" if change > 0 else "frost_shorter"].format(
            recent=day(lang, fr["recent"]["last_spring_frost"]),
            base=day(lang, fr["baseline"]["last_spring_frost"]), d=abs(change)))

    # 3. crops
    for c in crops:
        sow = c.get("sowing")
        if sow and abs(sow["shift_days"]) >= 5:
            add("crops", "info", t["sowing"].format(crop=name(c), base=day(lang, sow["baseline"]), recent=day(lang, sow["recent"]),
                                                    d=sow["shift_days"]))
    for c in sorted(crops, key=lambda c: -c["recent"]["heat_years_share"])[:2]:
        if c["recent"]["heat_years_share"] >= 0.2 and c["baseline"]:
            add("crops", "critical" if c["recent"]["heat_years_share"] >= 0.5 else "warning", t["crop_stress"].format(
                crop=name(c), share=c["recent"]["heat_years_share"], limit=c["heat_rule"]["limit_days"],
                thr=c["heat_rule"]["tmax_c"], before=c["baseline"]["heat_years_share"]))

    # 4. now
    rec, fc, out_ = now.get("recent"), now.get("forecast"), now.get("outlook")
    if rec and rec["rain_percentile"] is not None:
        if rec["rain_percentile"] <= 25:
            add("now", "warning", t["now_dry"].format(rain=rec["rain_mm"], pct=100 - rec["rain_percentile"]))
        elif rec["rain_percentile"] >= 75:
            add("now", "info", t["now_wet"].format(rain=rec["rain_mm"], pct=rec["rain_percentile"]))
    if fc:
        if fc["next_rain_date"]:
            add("now", "info", t["next_rain"].format(src=fc["source"], date=day(lang, fc["next_rain_date"]),
                                                     mm=fc["next_rain_mm"], week=fc["rain_7d_mm"]))
        else:
            add("now", "warning", t["no_rain"].format(src=fc["source"], n=fc["horizon_days"]))
    elif out_:
        add("now", "info", t["usual_rain"].format(days=out_["days_to_rain"]["p50"],
                                                  prob=out_["rain_within_7d_probability"]))
    for w in now.get("week") or []:
        if w["net_mm"] >= 1:
            add("now", "tip", t["week"].format(crop=name(w), mm=w["net_mm"], m3=w["m3_ha"]))
    return out

"""Patient-facing text catalogue (NFR-9). The assistant never free-writes replies (ADR-0006).

Every key exists in gu, hi and en (enforced by tests, together with WhatsApp length limits).
Gujarati and Hindi wording is a first draft and MUST be reviewed by native speakers before pilot.

`META_TEMPLATES` lists the business-initiated templates that must be submitted to Meta for approval
(BR-9); their `{{n}}` parameters are filled in the order given.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

Lang = str  # "gu" | "hi" | "en"
LANGS = ("gu", "hi", "en")
NOTICE_VERSION = "2026-11-v1"

T: dict[str, dict[Lang, str]] = {
    "consent_notice": {
        "en": "Namaste! This is {clinic}'s booking assistant on WhatsApp. To book, we store your name, age and "
        "phone number and use them only for your appointments at {clinic}. Privacy notice: {privacy_url}\n"
        "Tap *Agree* to continue.",
        "hi": "नमस्ते! यह {clinic} का WhatsApp बुकिंग सहायक है। बुकिंग के लिए हम आपका नाम, उम्र और फ़ोन नंबर रखते हैं "
        "और इनका उपयोग केवल {clinic} में आपकी अपॉइंटमेंट के लिए करते हैं। गोपनीयता सूचना: {privacy_url}\n"
        "आगे बढ़ने के लिए *सहमत* दबाएँ।",
        "gu": "નમસ્તે! આ {clinic} નો WhatsApp બુકિંગ સહાયક છે. બુકિંગ માટે અમે તમારું નામ, ઉંમર અને ફોન નંબર "
        "રાખીએ છીએ અને તેનો ઉપયોગ ફક્ત {clinic} માં તમારી એપોઇન્ટમેન્ટ માટે કરીએ છીએ. ગોપનીયતા સૂચના: "
        "{privacy_url}\nઆગળ વધવા માટે *સંમત* દબાવો.",
    },
    "btn_agree": {"en": "Agree", "hi": "सहमत", "gu": "સંમત"},
    "btn_decline": {"en": "No thanks", "hi": "नहीं", "gu": "ના"},
    "consent_declined": {
        "en": "Okay, we won't store your details. You can call the clinic on {clinic_phone}. "
        "Send *Hi* any time if you change your mind.",
        "hi": "ठीक है, हम आपकी जानकारी नहीं रखेंगे। आप क्लिनिक को {clinic_phone} पर कॉल कर सकते हैं। मन बदले तो कभी भी *Hi* भेजें।",
        "gu": "ઠીક છે, અમે તમારી માહિતી રાખીશું નહીં. તમે ક્લિનિકને {clinic_phone} પર ફોન કરી શકો છો. "
        "વિચાર બદલાય તો ગમે ત્યારે *Hi* મોકલો.",
    },
    "menu": {"en": "How can we help you?", "hi": "हम आपकी क्या मदद कर सकते हैं?", "gu": "અમે તમારી શું મદદ કરી શકીએ?"},
    "menu_button": {"en": "Options", "hi": "विकल्प", "gu": "વિકલ્પો"},
    "row_book": {"en": "Book appointment", "hi": "अपॉइंटमेंट बुक करें", "gu": "એપોઇન્ટમેન્ટ બુક કરો"},
    "row_manage": {"en": "Reschedule / cancel", "hi": "बदलें / रद्द करें", "gu": "બદલો / રદ કરો"},
    "row_token": {"en": "Get queue token", "hi": "कतार टोकन लें", "gu": "કતાર ટોકન લો"},
    "row_queue": {"en": "My token status", "hi": "मेरे टोकन की स्थिति", "gu": "મારા ટોકનની સ્થિતિ"},
    "row_info": {"en": "Timings & address", "hi": "समय और पता", "gu": "સમય અને સરનામું"},
    "row_staff": {"en": "Talk to clinic staff", "hi": "स्टाफ़ से बात करें", "gu": "સ્ટાફ સાથે વાત કરો"},
    "row_other_day": {"en": "Another day", "hi": "दूसरा दिन", "gu": "બીજો દિવસ"},
    "row_someone_else": {"en": "Someone else", "hi": "कोई और", "gu": "બીજું કોઈ"},
    "pick_doctor": {
        "en": "Which doctor would you like to see?",
        "hi": "आप किस डॉक्टर से मिलना चाहते हैं?",
        "gu": "તમે કયા ડૉક્ટરને મળવા માંગો છો?",
    },
    "pick_date": {"en": "Choose a day:", "hi": "दिन चुनें:", "gu": "દિવસ પસંદ કરો:"},
    "days_button": {"en": "Days", "hi": "दिन", "gu": "દિવસ"},
    "pick_slot": {"en": "Free times on {date}:", "hi": "{date} को खाली समय:", "gu": "{date} ના ખાલી સમય:"},
    "times_button": {"en": "Times", "hi": "समय", "gu": "સમય"},
    "no_slots": {
        "en": "Sorry, there are no free times on {date}. Please pick another day.",
        "hi": "माफ़ कीजिए, {date} को कोई खाली समय नहीं है। कृपया दूसरा दिन चुनें।",
        "gu": "માફ કરશો, {date} ના કોઈ ખાલી સમય નથી. કૃપા કરીને બીજો દિવસ પસંદ કરો.",
    },
    "no_days": {
        "en": "Sorry, there are no free appointments in the next {days} days. The clinic staff will contact you.",
        "hi": "माफ़ कीजिए, अगले {days} दिनों में कोई खाली अपॉइंटमेंट नहीं है। क्लिनिक स्टाफ़ आपसे संपर्क करेगा।",
        "gu": "માફ કરશો, આગામી {days} દિવસમાં કોઈ ખાલી એપોઇન્ટમેન્ટ નથી. ક્લિનિક સ્ટાફ તમારો સંપર્ક કરશે.",
    },
    "which_patient": {
        "en": "Who is the appointment for?",
        "hi": "अपॉइंटमेंट किसके लिए है?",
        "gu": "એપોઇન્ટમેન્ટ કોના માટે છે?",
    },
    "patients_button": {"en": "Choose", "hi": "चुनें", "gu": "પસંદ કરો"},
    "ask_name": {
        "en": "Please send the patient's full name.",
        "hi": "कृपया मरीज़ का पूरा नाम भेजें।",
        "gu": "કૃપા કરીને દર્દીનું પૂરું નામ મોકલો.",
    },
    "ask_age": {
        "en": "Please send the patient's age in years.",
        "hi": "कृपया मरीज़ की उम्र (वर्षों में) भेजें।",
        "gu": "કૃપા કરીને દર્દીની ઉંમર (વર્ષમાં) મોકલો.",
    },
    "bad_age": {
        "en": "Please send the age as a number, for example 42.",
        "hi": "कृपया उम्र अंकों में भेजें, जैसे 42।",
        "gu": "કૃપા કરીને ઉંમર આંકડામાં મોકલો, જેમ કે 42.",
    },
    "booked": {
        "en": "✅ Booked: {doctor}, {date} at {time}.\n{clinic}, {address}\n{map_url}\n"
        "Send *Menu* to reschedule or cancel.",
        "hi": "✅ बुक हो गया: {doctor}, {date}, {time}।\n{clinic}, {address}\n{map_url}\n"
        "बदलने या रद्द करने के लिए *Menu* भेजें।",
        "gu": "✅ બુક થઈ ગયું: {doctor}, {date}, {time}.\n{clinic}, {address}\n{map_url}\nબદલવા કે રદ કરવા *Menu* મોકલો.",
    },
    "ask_reminders": {
        "en": "Would you like appointment reminders and check-up messages from {clinic}? You can send STOP any time.",
        "hi": "क्या आप {clinic} से अपॉइंटमेंट रिमाइंडर और चेक-अप संदेश पाना चाहते हैं? आप कभी भी STOP भेज सकते हैं।",
        "gu": "શું તમે {clinic} તરફથી એપોઇન્ટમેન્ટ રિમાઇન્ડર અને ચેક-અપ સંદેશા મેળવવા માંગો છો? તમે ગમે ત્યારે STOP મોકલી શકો છો.",
    },
    "btn_yes": {"en": "Yes", "hi": "हाँ", "gu": "હા"},
    "btn_no": {"en": "No", "hi": "नहीं", "gu": "ના"},
    "reminders_on": {
        "en": "Done — we'll remind you.",
        "hi": "ठीक है — हम आपको याद दिलाएँगे।",
        "gu": "સારું — અમે તમને યાદ કરાવીશું.",
    },
    "reminders_off": {
        "en": "Okay, no reminders or check-up messages.",
        "hi": "ठीक है, कोई रिमाइंडर या चेक-अप संदेश नहीं भेजा जाएगा।",
        "gu": "ઠીક છે, કોઈ રિમાઇન્ડર કે ચેક-અપ સંદેશા મોકલવામાં આવશે નહીં.",
    },
    "slot_taken": {
        "en": "Sorry, that time was just taken. Please pick another time:",
        "hi": "माफ़ कीजिए, यह समय अभी-अभी बुक हो गया। कृपया दूसरा समय चुनें:",
        "gu": "માફ કરશો, આ સમય હમણાં જ બુક થઈ ગયો. કૃપા કરીને બીજો સમય પસંદ કરો:",
    },
    "limit_reached": {
        "en": "You already have {limit} upcoming appointments with this doctor. Send *Menu* to manage them.",
        "hi": "इस डॉक्टर के साथ आपकी पहले से {limit} आने वाली अपॉइंटमेंट हैं। उन्हें बदलने के लिए *Menu* भेजें।",
        "gu": "આ ડૉક્ટર સાથે તમારી પહેલેથી {limit} આગામી એપોઇન્ટમેન્ટ છે. તેને બદલવા *Menu* મોકલો.",
    },
    "too_late_change": {
        "en": "Changes are allowed until {minutes} minutes before the appointment. Please call the clinic on "
        "{clinic_phone}.",
        "hi": "अपॉइंटमेंट से {minutes} मिनट पहले तक ही बदलाव हो सकता है। कृपया क्लिनिक को {clinic_phone} पर कॉल करें।",
        "gu": "એપોઇન્ટમેન્ટના {minutes} મિનિટ પહેલાં સુધી જ ફેરફાર થઈ શકે છે. કૃપા કરીને ક્લિનિકને {clinic_phone} પર ફોન કરો.",
    },
    "cannot_book": {
        "en": "Sorry, that booking is not possible. Please choose another option or call {clinic_phone}.",
        "hi": "माफ़ कीजिए, यह बुकिंग संभव नहीं है। कृपया दूसरा विकल्प चुनें या {clinic_phone} पर कॉल करें।",
        "gu": "માફ કરશો, આ બુકિંગ શક્ય નથી. કૃપા કરીને બીજો વિકલ્પ પસંદ કરો અથવા {clinic_phone} પર ફોન કરો.",
    },
    "pick_appointment": {"en": "Which appointment?", "hi": "कौन-सी अपॉइंटमेंट?", "gu": "કઈ એપોઇન્ટમેન્ટ?"},
    "no_appointments": {
        "en": "You have no upcoming appointments. Send *Menu* to book.",
        "hi": "आपकी कोई आने वाली अपॉइंटमेंट नहीं है। बुक करने के लिए *Menu* भेजें।",
        "gu": "તમારી કોઈ આગામી એપોઇન્ટમેન્ટ નથી. બુક કરવા *Menu* મોકલો.",
    },
    "manage_actions": {
        "en": "{doctor}, {date} {time}. What would you like to do?",
        "hi": "{doctor}, {date} {time}। आप क्या करना चाहते हैं?",
        "gu": "{doctor}, {date} {time}. તમે શું કરવા માંગો છો?",
    },
    "btn_reschedule": {"en": "Reschedule", "hi": "समय बदलें", "gu": "સમય બદલો"},
    "btn_cancel": {"en": "Cancel", "hi": "रद्द करें", "gu": "રદ કરો"},
    "cancelled": {
        "en": "Your appointment on {date} at {time} is cancelled.",
        "hi": "{date} {time} की आपकी अपॉइंटमेंट रद्द कर दी गई है।",
        "gu": "{date} {time} ની તમારી એપોઇન્ટમેન્ટ રદ કરવામાં આવી છે.",
    },
    "token_issued": {
        "en": "Your token is *{token}* for {doctor}. {ahead} patients ahead, about {wait} min. Live status: {link}",
        "hi": "{doctor} के लिए आपका टोकन *{token}* है। आपसे पहले {ahead} मरीज़, लगभग {wait} मिनट। लाइव स्थिति: {link}",
        "gu": "{doctor} માટે તમારો ટોકન *{token}* છે. તમારી પહેલાં {ahead} દર્દી, આશરે {wait} મિનિટ. લાઇવ સ્થિતિ: {link}",
    },
    "token_alert": {
        "en": "Your turn is near: token *{token}*, {ahead} patients ahead. Please be at the clinic.",
        "hi": "आपकी बारी नज़दीक है: टोकन *{token}*, आपसे पहले {ahead} मरीज़। कृपया क्लिनिक पहुँच जाएँ।",
        "gu": "તમારો વારો નજીક છે: ટોકન *{token}*, તમારી પહેલાં {ahead} દર્દી. કૃપા કરીને ક્લિનિક પર આવી જાઓ.",
    },
    "queue_status": {
        "en": "Token {token}: now serving {current}. {ahead} ahead, about {wait} min.",
        "hi": "टोकन {token}: अभी {current} नंबर चल रहा है। आपसे पहले {ahead}, लगभग {wait} मिनट।",
        "gu": "ટોકન {token}: હાલમાં {current} નંબર ચાલે છે. તમારી પહેલાં {ahead}, આશરે {wait} મિનિટ.",
    },
    "no_token": {
        "en": "You don't have a token today. Send *Menu* and choose Get queue token.",
        "hi": "आज आपका कोई टोकन नहीं है। *Menu* भेजें और कतार टोकन लें चुनें।",
        "gu": "આજે તમારો કોઈ ટોકન નથી. *Menu* મોકલો અને કતાર ટોકન લો પસંદ કરો.",
    },
    "token_not_open": {
        "en": "Tokens open {minutes} minutes before the session starts.",
        "hi": "टोकन सत्र शुरू होने से {minutes} मिनट पहले मिलने शुरू होंगे।",
        "gu": "ટોકન સત્ર શરૂ થવાના {minutes} મિનિટ પહેલાંથી મળશે.",
    },
    "token_closed": {
        "en": "Tokens are not available for this session any more.",
        "hi": "इस सत्र के टोकन अब उपलब्ध नहीं हैं।",
        "gu": "આ સત્રના ટોકન હવે ઉપલબ્ધ નથી.",
    },
    "clinic_info": {
        "en": "{clinic}\n📍 {address}\n{map_url}\n📞 {clinic_phone}\nTimings:\n{timings}\nConsultation fee: ₹{fee}",
        "hi": "{clinic}\n📍 {address}\n{map_url}\n📞 {clinic_phone}\nसमय:\n{timings}\nपरामर्श शुल्क: ₹{fee}",
        "gu": "{clinic}\n📍 {address}\n{map_url}\n📞 {clinic_phone}\nસમય:\n{timings}\nકન્સલ્ટેશન ફી: ₹{fee}",
    },
    "handover_ack": {
        "en": "Thank you. A member of the clinic staff will reply here shortly.",
        "hi": "धन्यवाद। क्लिनिक स्टाफ़ जल्द ही यहीं जवाब देगा।",
        "gu": "આભાર. ક્લિનિક સ્ટાફ ટૂંક સમયમાં અહીં જ જવાબ આપશે.",
    },
    "medical_deferral": {
        "en": "We can't give medical advice on WhatsApp. A member of the clinic staff will reply here shortly. "
        "If it is urgent, call {clinic_phone}.",
        "hi": "हम WhatsApp पर चिकित्सा सलाह नहीं दे सकते। क्लिनिक स्टाफ़ जल्द ही यहीं जवाब देगा। "
        "ज़रूरी हो तो {clinic_phone} पर कॉल करें।",
        "gu": "અમે WhatsApp પર તબીબી સલાહ આપી શકતા નથી. ક્લિનિક સ્ટાફ ટૂંક સમયમાં અહીં જ જવાબ આપશે. "
        "તાત્કાલિક હોય તો {clinic_phone} પર ફોન કરો.",
    },
    # FR-8.3: never claims emergency services were contacted; only that clinic staff were alerted (true).
    "emergency": {
        "en": "🚨 This may be an emergency. Please call 108 (ambulance) or 112 right now, or go to the nearest "
        "hospital. You can also call the clinic on {clinic_phone}. We have alerted the clinic staff.",
        "hi": "🚨 यह आपात स्थिति हो सकती है। कृपया तुरंत 108 (एम्बुलेंस) या 112 पर कॉल करें, या नज़दीकी अस्पताल जाएँ। "
        "आप क्लिनिक को {clinic_phone} पर भी कॉल कर सकते हैं। हमने क्लिनिक स्टाफ़ को सूचित कर दिया है।",
        "gu": "🚨 આ ઇમરજન્સી હોઈ શકે છે. કૃપા કરીને તરત જ 108 (એમ્બ્યુલન્સ) અથવા 112 પર ફોન કરો, અથવા નજીકની "
        "હોસ્પિટલ જાઓ. તમે ક્લિનિકને {clinic_phone} પર પણ ફોન કરી શકો છો. અમે ક્લિનિક સ્ટાફને જાણ કરી છે.",
    },
    "opted_out": {
        "en": "You will not receive reminders or check-up messages from {clinic}. You can still book any time by "
        "sending *Hi*.",
        "hi": "अब आपको {clinic} से रिमाइंडर या चेक-अप संदेश नहीं मिलेंगे। बुकिंग के लिए कभी भी *Hi* भेजें।",
        "gu": "હવે તમને {clinic} તરફથી રિમાઇન્ડર કે ચેક-અપ સંદેશા મળશે નહીં. બુકિંગ માટે ગમે ત્યારે *Hi* મોકલો.",
    },
    "opted_in": {
        "en": "Welcome back — reminders and check-up messages are on again.",
        "hi": "स्वागत है — रिमाइंडर और चेक-अप संदेश फिर से चालू हैं।",
        "gu": "સ્વાગત છે — રિમાઇન્ડર અને ચેક-અપ સંદેશા ફરી ચાલુ છે.",
    },
    "voice_unsupported": {
        "en": "Sorry, we can't listen to voice notes yet. Please type or tap an option.",
        "hi": "माफ़ कीजिए, हम अभी वॉइस नोट नहीं सुन सकते। कृपया लिखें या विकल्प चुनें।",
        "gu": "માફ કરશો, અમે હજી વૉઇસ નોટ સાંભળી શકતા નથી. કૃપા કરીને લખો અથવા વિકલ્પ પસંદ કરો.",
    },
    "unknown": {
        "en": "Sorry, I didn't understand. Please choose an option:",
        "hi": "माफ़ कीजिए, मैं समझ नहीं पाया। कृपया एक विकल्प चुनें:",
        "gu": "માફ કરશો, હું સમજી શક્યો નહીં. કૃપા કરીને એક વિકલ્પ પસંદ કરો:",
    },
    "noshow_rebook": {
        "en": "We missed you today at {clinic}. Would you like to book another time?",
        "hi": "आज हम {clinic} में आपका इंतज़ार कर रहे थे। क्या आप दूसरा समय बुक करना चाहेंगे?",
        "gu": "આજે અમે {clinic} માં તમારી રાહ જોતા હતા. શું તમે બીજો સમય બુક કરવા માંગો છો?",
    },
    "btn_book_again": {"en": "Book again", "hi": "फिर से बुक करें", "gu": "ફરી બુક કરો"},
    "reminder": {
        "en": "Reminder: your appointment at {clinic} with {doctor} is on {date} at {time}. Please confirm.",
        "hi": "रिमाइंडर: {clinic} में {doctor} के साथ आपकी अपॉइंटमेंट {date} को {time} बजे है। कृपया पुष्टि करें।",
        "gu": "યાદ અપાવીએ: {clinic} માં {doctor} સાથે તમારી એપોઇન્ટમેન્ટ {date} ના {time} વાગ્યે છે. કૃપા કરીને પુષ્ટિ કરો.",
    },
    "btn_confirm": {"en": "Confirm", "hi": "पुष्टि करें", "gu": "પુષ્ટિ કરો"},
    "confirmed_ack": {
        "en": "Thank you, your appointment is confirmed.",
        "hi": "धन्यवाद, आपकी अपॉइंटमेंट की पुष्टि हो गई है।",
        "gu": "આભાર, તમારી એપોઇન્ટમેન્ટની પુષ્ટિ થઈ ગઈ છે.",
    },
    "recall_due": {
        "en": "It's time for your {label} at {clinic}. Would you like to book a visit?",
        "hi": "{clinic} में आपके {label} का समय हो गया है। क्या आप अपॉइंटमेंट बुक करना चाहेंगे?",
        "gu": "{clinic} માં તમારા {label} નો સમય થઈ ગયો છે. શું તમે એપોઇન્ટમેન્ટ બુક કરવા માંગો છો?",
    },
    "btn_book_now": {"en": "Book now", "hi": "अभी बुक करें", "gu": "હમણાં બુક કરો"},
    "btn_not_now": {"en": "Not now", "hi": "अभी नहीं", "gu": "હમણાં નહીં"},
    "recall_declined": {
        "en": "Okay. Send *Hi* whenever you'd like to book.",
        "hi": "ठीक है। जब भी बुक करना हो, *Hi* भेजें।",
        "gu": "ઠીક છે. જ્યારે પણ બુક કરવું હોય ત્યારે *Hi* મોકલો.",
    },
    "missed_call_offer": {
        "en": "Sorry we missed your call at {clinic}! Would you like to book an appointment? Tap below or reply here.",
        "hi": "माफ़ कीजिए, हम {clinic} में आपकी कॉल नहीं उठा पाए! क्या आप अपॉइंटमेंट बुक करना चाहेंगे? नीचे टैप करें या यहीं जवाब दें।",
        "gu": "માફ કરશો, અમે {clinic} માં તમારો કૉલ ઉપાડી શક્યા નહીં! શું તમે એપોઇન્ટમેન્ટ બુક કરવા માંગો છો? નીચે ટૅપ કરો "
        "અથવા અહીં જ જવાબ આપો.",
    },
    "btn_book_appt": {"en": "Book appointment", "hi": "बुक करें", "gu": "બુક કરો"},
    "btn_call_me": {"en": "Call me back", "hi": "मुझे कॉल करें", "gu": "મને ફોન કરો"},
    "callback_ack": {
        "en": "Thanks — the clinic will call you back shortly.",
        "hi": "धन्यवाद — क्लिनिक आपको जल्द ही वापस कॉल करेगा।",
        "gu": "આભાર — ક્લિનિક તમને ટૂંક સમયમાં પાછો ફોન કરશે.",
    },
    "staff_alert": {  # to clinic staff; English dashboard language (NFR-9)
        "en": "ClinicDesk alert: {reason} message from a patient ({phone}). Open the inbox: {link}",
        "hi": "ClinicDesk alert: {reason} message from a patient ({phone}). Open the inbox: {link}",
        "gu": "ClinicDesk alert: {reason} message from a patient ({phone}). Open the inbox: {link}",
    },
}

# Business-initiated messages need Meta-approved templates (BR-9). name → ordered params.
META_TEMPLATES: dict[str, list[str]] = {
    "noshow_rebook": ["clinic"],
    "token_alert": ["token", "ahead"],
    "token_issued": ["token", "doctor", "ahead", "wait", "link"],
    "staff_alert": ["reason", "phone", "link"],
    "appointment_reminder": ["clinic", "doctor", "date", "time"],  # body = catalogue "reminder"
    "recall_due": ["label", "clinic"],
    "missed_call_offer": ["clinic"],
}
TEMPLATE_BODY = {"appointment_reminder": "reminder"}  # Meta template name → catalogue key when they differ

WEEKDAYS: dict[Lang, list[str]] = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "hi": ["सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"],
    "gu": ["સોમ", "મંગળ", "બુધ", "ગુરુ", "શુક્ર", "શનિ", "રવિ"],
}
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def lang_or_default(lang: str | None) -> Lang:
    return lang if lang in LANGS else "en"


def t(key: str, lang: str | None, **params: Any) -> str:
    text = T[key][lang_or_default(lang)]
    return text.format(**params) if params else text


def fmt_date(at: datetime, tz: ZoneInfo, lang: str | None) -> str:
    local = at.astimezone(tz)
    wd = WEEKDAYS[lang_or_default(lang)][local.weekday()]
    if lang_or_default(lang) == "en":
        return f"{wd} {local.day} {MONTHS_EN[local.month - 1]}"
    return f"{wd} {local.day}/{local.month}"


def fmt_time(at: datetime, tz: ZoneInfo) -> str:
    local = at.astimezone(tz)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def template_ref(name: str, lang: str | None, **params: Any) -> dict[str, Any]:
    order = META_TEMPLATES[name]
    return {"name": name, "language": lang_or_default(lang), "params": [str(params[p]) for p in order]}

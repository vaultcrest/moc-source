const BL_COUNTRIES = ["Afghanistan","Albania","Algeria","Andorra","Angola","Anguilla","Antigua and Barbuda","Argentina","Armenia","Aruba","Australia","Austria","Azerbaijan","Bahamas","Bahrain","Bangladesh","Barbados","Belgium","Belize","Benin","Bermuda","Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","British Indian Ocean Territory","Brunei","Bulgaria","Burkina Faso","Burundi","Cambodia","Cameroon","Canada","Cape Verde","Caribbean Netherlands","Cayman Islands","Central African Republic","Chad","Chile","Colombia","Comoros","Congo","Congo (DRC)","Cook Islands","Costa Rica","Cote D'Ivoire","Croatia","Curacao","Cyprus","Czech Republic","Denmark","Djibouti","Dominica","Dominican Republic","East Timor","Ecuador","Egypt","El Salvador","Equatorial Guinea","Eritrea","Estonia","Ethiopia","Falkland Islands (Islas Malvinas)","Faroe Islands","Fiji","Finland","France","French Polynesia","Gabon","Gambia","Georgia","Germany","Ghana","Gibraltar","Greece","Greenland","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana","Haiti","Honduras","Hong Kong SAR China","Hungary","Iceland","India","Indonesia","Iraq","Ireland","Israel","Italy","Jamaica","Japan","Jordan","Kazakhstan","Kenya","Kiribati","Kuwait","Kyrgyzstan","Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein","Lithuania","Luxembourg","Macau","Macedonia","Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands","Mauritania","Mauritius","Mayotte","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Montserrat","Morocco","Mozambique","Myanmar","Namibia","Nauru","Nepal","Netherlands","New Caledonia","New Zealand","Nicaragua","Niger","Niue","Norfolk Island","Norway","Oman","Pakistan","Palau","Panama","Papua new Guinea","Paraguay","Peru","Philippines","Pitcairn Islands","Poland","Portugal","Qatar","Romania","Rwanda","Samoa","San Marino","Sao Tome and Principe","Saudi Arabia","Senegal","Serbia","Seychelles","Sierra Leone","Singapore","Sint Maarten","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Georgia","South Korea","Spain","Sri Lanka","St. Helena","St. Kitts and Nevis","St. Lucia","St. Pierre and Miquelon","St. Vincent and the Grenadines","Sudan","Suriname","Svalbard and Jan Mayen","Swaziland","Sweden","Switzerland","Taiwan Region","Tajikistan","Tanzania","Thailand","Togo","Tonga","Trinidad and Tobago","Tunisia","Turkey","Turkmenistan","Turks and Caicos Islands","Tuvalu","Uganda","Ukraine","United Arab Emirates","United Kingdom","Uruguay","USA","Uzbekistan","Vanuatu","Vatican City State","Venezuela","Vietnam","Virgin Islands (British)","Wallis and Futuna","Yemen","Zambia","Zimbabwe"];

const DEFAULTS = {
  storeLocation:      null, // null = auto-detect on first load
  pabRegion:          null, // null = auto-detect from timezone on first load
  filterLotsOverMax:  true,
  filterLotsBelowQty: false,
};

function guessPabLocale() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const exact = {
    "America/New_York":             "en-us",
    "America/Chicago":              "en-us",
    "America/Denver":               "en-us",
    "America/Los_Angeles":          "en-us",
    "America/Phoenix":              "en-us",
    "America/Anchorage":            "en-us",
    "Pacific/Honolulu":             "en-us",
    "America/Indiana/Indianapolis": "en-us",
    "America/Toronto":              "en-ca",
    "America/Vancouver":            "en-ca",
    "America/Halifax":              "en-ca",
    "Europe/London":                "en-gb",
    "Europe/Berlin":                "de-de",
    "Europe/Paris":                 "fr-fr",
    "Europe/Amsterdam":             "nl-nl",
    "Europe/Stockholm":             "sv-se",
    "Europe/Oslo":                  "nb-no",
    "Europe/Copenhagen":            "da-dk",
    "Europe/Helsinki":              "fi-fi",
    "Europe/Warsaw":                "pl-pl",
    "Europe/Prague":                "cs-cz",
    "Europe/Madrid":                "es-es",
    "Europe/Rome":                  "it-it",
    "Europe/Lisbon":                "pt-pt",
    "Australia/Sydney":             "en-au",
    "Australia/Melbourne":          "en-au",
    "Australia/Perth":              "en-au",
    "Pacific/Auckland":             "en-nz",
  }[tz];
  if (exact) return exact;
  if (tz.startsWith("America/"))   return "en-us";
  if (tz.startsWith("Europe/"))    return "en-gb";
  if (tz.startsWith("Australia/")) return "en-au";
  if (tz.startsWith("Pacific/"))   return "en-nz";
  return "en-us";
}

// Map Intl timezone → BrickLink store location value
function guessLocation() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const exact = {
    "America/New_York":             "country:USA",
    "America/Chicago":              "country:USA",
    "America/Denver":               "country:USA",
    "America/Los_Angeles":          "country:USA",
    "America/Phoenix":              "country:USA",
    "America/Anchorage":            "country:USA",
    "Pacific/Honolulu":             "country:USA",
    "America/Indiana/Indianapolis": "country:USA",
    "America/Toronto":              "country:Canada",
    "America/Vancouver":            "country:Canada",
    "America/Halifax":              "country:Canada",
    "Europe/London":                "country:United Kingdom",
    "Europe/Berlin":                "country:Germany",
    "Europe/Paris":                 "country:France",
    "Europe/Amsterdam":             "country:Netherlands",
    "Europe/Stockholm":             "country:Sweden",
    "Europe/Oslo":                  "country:Norway",
    "Europe/Copenhagen":            "country:Denmark",
    "Europe/Helsinki":              "country:Finland",
    "Australia/Sydney":             "country:Australia",
    "Australia/Melbourne":          "country:Australia",
    "Australia/Perth":              "country:Australia",
    "Asia/Tokyo":                   "country:Japan",
    "Asia/Seoul":                   "country:South Korea",
  }[tz];
  if (exact) return exact;

  if (tz.startsWith("America/"))   return "region:North America";
  if (tz.startsWith("Europe/"))    return "region:Europe";
  if (tz.startsWith("Australia/")) return "region:Australia & Oceania";
  if (tz.startsWith("Pacific/"))   return "region:Australia & Oceania";
  if (tz.startsWith("Asia/"))      return "region:Asia";
  if (tz.startsWith("Africa/"))    return "region:Africa";
  return "anywhere";
}

function showSaved() {
  const el = document.getElementById("savedMsg");
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 1500);
}

function buildCountryOptions(currentValue) {
  const group = document.getElementById("countryGroup");
  group.innerHTML = "";
  for (const name of BL_COUNTRIES) {
    const opt = document.createElement("option");
    opt.value = `country:${name}`;
    opt.textContent = name;
    group.appendChild(opt);
  }
  if (currentValue?.startsWith("country:")) {
    document.getElementById("storeLocation").value = currentValue;
  }
}

async function load() {
  const sync = await chrome.storage.sync.get(DEFAULTS);

  let loc = sync.storeLocation ?? guessLocation();
  let pabLocale = sync.pabRegion ?? guessPabLocale();

  buildCountryOptions(loc);

  document.getElementById("storeLocation").value = loc;
  document.getElementById("pabRegion").value = pabLocale;
  document.getElementById("filterLotsOverMax").checked  = sync.filterLotsOverMax;
  document.getElementById("filterLotsBelowQty").checked = sync.filterLotsBelowQty;

  const saves = {};
  if (sync.storeLocation === null) saves.storeLocation = loc;
  if (sync.pabRegion === null) saves.pabRegion = pabLocale;
  if (Object.keys(saves).length) await chrome.storage.sync.set(saves);
}

async function save() {
  await chrome.storage.sync.set({
    storeLocation:      document.getElementById("storeLocation").value,
    pabRegion:          document.getElementById("pabRegion").value,
    filterLotsOverMax:  document.getElementById("filterLotsOverMax").checked,
    filterLotsBelowQty: document.getElementById("filterLotsBelowQty").checked,
  });
  showSaved();
}

document.getElementById("storeLocation").addEventListener("change", save);
document.getElementById("pabRegion").addEventListener("change", save);
document.getElementById("filterLotsOverMax").addEventListener("change", save);
document.getElementById("filterLotsBelowQty").addEventListener("change", save);

load();

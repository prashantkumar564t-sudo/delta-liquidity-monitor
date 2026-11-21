/**
 * Delta Evening Options Microstructure Trigger
 * Google Apps Script standalone runner for prashantkumar564t-sudo/delta-liquidity-monitor
 */

const REPO_OWNER = "prashantkumar564t-sudo";
const REPO_NAME = "delta-liquidity-monitor";
const WORKFLOW_FILE = "delta_evening_collector.yml";

/**
 * Dispatches GitHub Actions workflow for 5-hour evening collection run.
 */
function triggerDeltaEveningRun() {
  const scriptProperties = PropertiesService.getScriptProperties();
  const token = scriptProperties.getProperty("GITHUB_PAT");

  if (!token) {
    throw new Error(
      "GITHUB_PAT is not set in Script Properties! Please add it in Project Settings -> Script Properties."
    );
  }

  const url = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

  const payload = {
    ref: "main",
    inputs: {
      duration_minutes: "300"
    }
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Accept": "application/vnd.github.v3+json",
      "User-Agent": "Delta-GAS-Trigger"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  Logger.log(`Dispatching workflow: ${url}`);
  const response = UrlFetchApp.fetch(url, options);
  const statusCode = response.getResponseCode();
  const responseText = response.getContentText();

  Logger.log(`Response Code: ${statusCode}`);
  Logger.log(`Response Text: ${responseText}`);

  if (statusCode === 204) {
    Logger.log("✅ Successfully dispatched Delta Evening Collector workflow (300 min).");
    return { success: true, status: 204 };
  } else {
    Logger.log(`❌ Failed to dispatch workflow. Status: ${statusCode}, Body: ${responseText}`);
    throw new Error(`GitHub API Error (${statusCode}): ${responseText}`);
  }
}

/**
 * Sets up an idempotent daily time-driven trigger at 18:00 IST (6:00 PM).
 */
function setupDaily6PMTrigger() {
  const functionName = "triggerDeltaEveningRun";
  const existingTriggers = ScriptApp.getProjectTriggers();

  // Delete existing duplicate triggers
  existingTriggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === functionName) {
      Logger.log(`Deleting existing trigger ID: ${trigger.getUniqueId()}`);
      ScriptApp.deleteTrigger(trigger);
    }
  });

  // Create new daily trigger at 18:00 IST (nearHour 18)
  const newTrigger = ScriptApp.newTrigger(functionName)
    .timeBased()
    .everyDays(1)
    .atHour(18)
    .nearHour(18)
    .inTimezone("Asia/Kolkata")
    .create();

  Logger.log(`✅ Created daily 18:00 IST trigger: ${newTrigger.getUniqueId()}`);
  return newTrigger.getUniqueId();
}

async function updateStatus() {
  chrome.runtime.sendMessage({ action: "getStatus" }, (response) => {
    const badge = document.getElementById("statusBadge");
    const tabTitle = document.getElementById("activeTabTitle");
    const tabUrl = document.getElementById("activeTabUrl");

    if (response && response.connected) {
      badge.className = "status-badge connected";
      badge.textContent = "Connected";
    } else {
      badge.className = "status-badge disconnected";
      badge.textContent = "Disconnected";
    }

    if (response && response.activeTab) {
      tabTitle.textContent = response.activeTab.title || "Untitled";
      tabUrl.textContent = response.activeTab.url || "-";
    }
  });
}

document.getElementById("reconnectBtn").addEventListener("click", () => {
  chrome.runtime.sendMessage({ action: "reconnect" }, () => {
    setTimeout(updateStatus, 500);
  });
});

updateStatus();
setInterval(updateStatus, 2000);

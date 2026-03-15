/**
 * Sharing client — Socket.IO connection and share flow management.
 *
 * Connects to the NoteHelper gateway via Socket.IO for real-time sharing
 * of directories, partners, and notes between NoteHelper instances.
 *
 * Usage:
 *   Share.init()           — Connect to gateway (called on page load)
 *   Share.openShareModal() — Open the share modal with online users
 *   Share.getOnlineCount() — Get number of online peers
 */
const Share = (function () {
  let socket = null;
  let connected = false;
  let shareEnabled = false;  // true only after successful connect (passes allowlist)
  let onlineUsers = [];
  let pendingShareType = null;   // "directory", "partner", or "note"
  let pendingItemId = null;      // set when sharing a single partner or note
  let pendingRecipientEmail = null;

  // ── Connection ──────────────────────────────────────────────────────

  async function init() {
    try {
      const resp = await fetch('/api/share/connection-info');
      if (!resp.ok) return;
      const info = await resp.json();
      if (!info.success) return;

      socket = io(info.gateway_url + '/share', {
        auth: { token: info.token },
        transports: ['polling', 'websocket'],
        reconnection: true,
        reconnectionDelay: 5000,
        reconnectionAttempts: 10,
      });

      socket.on('connect', () => {
        connected = true;
        shareEnabled = true;
        _updateBadges();
        socket.emit('get_online_users');
      });

      socket.on('disconnect', () => {
        connected = false;
        onlineUsers = [];
        _updateBadges();
      });

      // Not on the allowlist — hide sharing UI entirely
      socket.on('not_allowed', () => {
        shareEnabled = false;
        _updateBadges();
      });

      socket.on('online_users', (data) => {
        onlineUsers = data.users || [];
        _updateBadges();
        _renderOnlineList();
      });

      // Incoming share offer
      socket.on('share_offer', (data) => {
        _showIncomingOffer(data);
      });

      // Our share was accepted — send the data
      socket.on('share_accepted', async (data) => {
        await _sendShareData(data.recipient_email);
      });

      // Our share was declined
      socket.on('share_declined', (data) => {
        _showToast(`${data.recipient_name} declined the share.`, 'warning');
        _resetShareState();
      });

      // Incoming shared data
      socket.on('share_payload', async (data) => {
        await _receiveShareData(data);
      });

      // Another tab already handled the offer
      socket.on('share_offer_handled', () => {
        const container = document.getElementById('shareOfferContainer');
        if (container) container.innerHTML = '';
      });

      socket.on('share_error', (data) => {
        _showToast(data.error || 'Share error', 'danger');
        _resetShareState();
      });

    } catch (e) {
      console.warn('Sharing unavailable:', e);
    }
  }

  // ── Share initiation ────────────────────────────────────────────────

  function openShareModal(type, itemId) {
    pendingShareType = type || 'directory';
    pendingItemId = (type === 'partner' || type === 'note') ? (itemId || null) : null;

    if (!connected || onlineUsers.length === 0) {
      _showToast('No teammates online right now. They need to be running NoteHelper too.', 'info');
      return;
    }

    _renderOnlineList();
    const modal = new bootstrap.Modal(document.getElementById('shareModal'));
    modal.show();
  }

  function sendShareRequest(recipientEmail) {
    if (!socket || !connected) return;

    pendingRecipientEmail = recipientEmail;
    const recipient = onlineUsers.find(u => u.email === recipientEmail);

    // Update modal to show "waiting" state
    const body = document.getElementById('shareModalBody');
    body.innerHTML = `
      <div class="text-center py-4">
        <div class="spinner-border text-primary mb-3" role="status"></div>
        <p>Waiting for <strong>${_esc(recipient?.name || 'recipient')}</strong> to accept...</p>
        <button class="btn btn-sm btn-outline-secondary" onclick="Share.cancelShare()">Cancel</button>
      </div>
    `;

    socket.emit('share_request', {
      recipient_email: recipientEmail,
      share_type: pendingShareType,
      item_name: pendingItemId ? document.title.replace(' - NoteHelper', '') : null,
    });
  }

  function cancelShare() {
    _resetShareState();
    bootstrap.Modal.getInstance(document.getElementById('shareModal'))?.hide();
  }

  // ── Sending data ────────────────────────────────────────────────────

  async function _sendShareData(recipientEmail) {
    // Capture and clear state atomically to prevent duplicate sends.
    const shareType = pendingShareType;
    const itemId = pendingItemId;
    _resetShareState();

    if (!shareType) return;

    try {
      if (shareType === 'note' && itemId) {
        const resp = await fetch(`/api/share/note/${itemId}`);
        const data = await resp.json();
        socket.emit('share_data', {
          recipient_email: recipientEmail,
          share_type: 'note',
          note: data.note,
        });
        _showToast('Note shared successfully!', 'success');
      } else if (shareType === 'partner' && itemId) {
        const resp = await fetch(`/api/share/partner/${itemId}`);
        const data = await resp.json();
        socket.emit('share_data', {
          recipient_email: recipientEmail,
          share_type: 'partner',
          partners: [data.partner],
        });
        _showToast('Sent 1 partner successfully!', 'success');
      } else if (shareType === 'directory') {
        const resp = await fetch('/api/share/directory');
        const data = await resp.json();
        const partners = data.partners;
        socket.emit('share_data', {
          recipient_email: recipientEmail,
          share_type: 'directory',
          partners: partners,
        });
        const count = partners.length;
        _showToast(`Sent ${count} partner${count !== 1 ? 's' : ''} successfully!`, 'success');
      }
    } catch (e) {
      _showToast('Failed to send share data: ' + e.message, 'danger');
    }
    bootstrap.Modal.getInstance(document.getElementById('shareModal'))?.hide();
  }

  // ── Receiving data ──────────────────────────────────────────────────

  async function _receiveShareData(data) {
    if (data.share_type === 'note' && data.note) {
      // Note import
      const customerName = data.note.customer?.name || 'General';
      _showToast(
        `Receiving note for ${_esc(customerName)} from ${_esc(data.sender_name)}...`,
        'info',
      );
      try {
        const resp = await fetch('/api/share/receive-note', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            note: data.note,
            sender_name: data.sender_name,
          }),
        });
        const result = await resp.json();
        if (result.success) {
          // Show what was created (seller, customer, etc.)
          if (result.created && result.created.length > 0) {
            _showToast(`Created: ${result.created.join(', ')}`, 'info');
          }
          const msg = result.customer_name
            ? `Note imported for ${_esc(result.customer_name)}!`
            : 'Note imported!';
          _showToast(msg, 'success');
          // Reload if on notes list or note view
          if (window.location.pathname === '/notes' ||
              window.location.pathname.startsWith('/note/')) {
            setTimeout(() => window.location.reload(), 1500);
          }
        } else {
          _showToast('Import failed: ' + (result.error || 'unknown error'), 'danger');
        }
      } catch (e) {
        _showToast('Import failed: ' + e.message, 'danger');
      }
      return;
    }

    // Partner directory / single partner import
    const count = (data.partners || []).length;
    _showToast(
      `Receiving ${count} partner${count !== 1 ? 's' : ''} from ${_esc(data.sender_name)}...`,
      'info',
    );

    try {
      const resp = await fetch('/api/share/receive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          partners: data.partners,
          sender_name: data.sender_name,
        }),
      });
      const result = await resp.json();
      if (result.success) {
        const msg = `Import complete: ${result.created} new, ${result.updated} updated` +
          (result.skipped ? `, ${result.skipped} skipped` : '');
        _showToast(msg, 'success');
        // Reload if we're on the partners page
        if (window.location.pathname === '/partners' ||
            window.location.pathname.startsWith('/partners/')) {
          setTimeout(() => window.location.reload(), 1500);
        }
      } else {
        _showToast('Import failed: ' + (result.error || 'unknown error'), 'danger');
      }
    } catch (e) {
      _showToast('Import failed: ' + e.message, 'danger');
    }
  }

  // ── Incoming offer UI ───────────────────────────────────────────────

  function _showIncomingOffer(data) {
    let typeLabel;
    if (data.share_type === 'note') {
      typeLabel = `a note${data.item_name ? ' "' + _esc(data.item_name) + '"' : ''}`;
    } else if (data.share_type === 'directory') {
      typeLabel = 'their partner directory';
    } else {
      typeLabel = `"${_esc(data.item_name || 'a partner')}"`;
    }

    // Create or reuse the offer toast container
    let container = document.getElementById('shareOfferContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'shareOfferContainer';
      container.className = 'position-fixed bottom-0 end-0 p-3';
      container.style.zIndex = '1090';
      document.body.appendChild(container);
    }

    const offerId = 'offer-' + Date.now();
    container.innerHTML = `
      <div id="${offerId}" class="toast show border-primary" role="alert"
           style="min-width: 350px;">
        <div class="toast-header bg-primary text-white">
          <i class="bi bi-share me-2"></i>
          <strong class="me-auto">Share</strong>
          <button type="button" class="btn-close btn-close-white" 
                  onclick="Share.declineOffer('${_esc(data.sender_email)}', '${offerId}')"></button>
        </div>
        <div class="toast-body">
          <p class="mb-2">
            <strong>${_esc(data.sender_name)}</strong> wants to share ${typeLabel} with you.
          </p>
          <div class="d-flex gap-2">
            <button class="btn btn-sm btn-success" 
                    onclick="Share.acceptOffer('${_esc(data.sender_email)}', '${offerId}')">
              <i class="bi bi-check-lg"></i> Accept
            </button>
            <button class="btn btn-sm btn-outline-secondary"
                    onclick="Share.declineOffer('${_esc(data.sender_email)}', '${offerId}')">
              Decline
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function acceptOffer(senderEmail, offerId) {
    socket.emit('share_accept', { sender_email: senderEmail });
    document.getElementById(offerId)?.remove();
    _showToast('Accepted — waiting for data...', 'info');
  }

  function declineOffer(senderEmail, offerId) {
    socket.emit('share_decline', { sender_email: senderEmail });
    document.getElementById(offerId)?.remove();
  }

  // ── UI helpers ──────────────────────────────────────────────────────

  function _renderOnlineList() {
    const body = document.getElementById('shareModalBody');
    if (!body) return;

    if (onlineUsers.length === 0) {
      body.innerHTML = `
        <div class="text-center text-muted py-4">
          <i class="bi bi-people fs-1 d-block mb-2"></i>
          <p>No teammates online right now.</p>
          <small>They need to be running NoteHelper with a valid sign-in.</small>
        </div>
      `;
      return;
    }

    // Search box + user list
    body.innerHTML = `
      <div class="mb-3">
        <input type="text" class="form-control" id="shareUserSearch"
               placeholder="Search by name or email..." autocomplete="off">
      </div>
      <div class="list-group" id="shareUserList">
        ${onlineUsers.map(u => `
          <button class="list-group-item list-group-item-action d-flex align-items-center share-user-item"
                  data-name="${_esc(u.name.toLowerCase())}" data-email="${_esc(u.email.toLowerCase())}"
                  onclick="Share.sendShareRequest('${_esc(u.email)}')">
            <i class="bi bi-person-circle fs-4 me-3 text-success"></i>
            <div>
              <div class="fw-semibold">${_esc(u.name)}</div>
              <small class="text-muted">${_esc(u.email)}</small>
            </div>
            <i class="bi bi-send ms-auto text-primary"></i>
          </button>
        `).join('')}
      </div>
    `;

    // Wire up search filtering
    const searchInput = document.getElementById('shareUserSearch');
    searchInput?.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll('.share-user-item').forEach(item => {
        const match = item.dataset.name.includes(q) || item.dataset.email.includes(q);
        item.style.display = match ? '' : 'none';
      });
    });
    searchInput?.focus();
  }

  function _updateBadges() {
    // Hide share buttons entirely if not on allowlist
    document.querySelectorAll('.btn-share').forEach(btn => {
      btn.style.display = shareEnabled ? '' : 'none';
    });

    // Update any online count badges on the page
    document.querySelectorAll('.share-online-count').forEach(el => {
      el.textContent = onlineUsers.length;
      el.style.display = (shareEnabled && onlineUsers.length > 0) ? '' : 'none';
    });
  }

  function _resetShareState() {
    pendingShareType = null;
    pendingItemId = null;
    pendingRecipientEmail = null;
  }

  function _showToast(message, type) {
    // Reuse Bootstrap toast pattern
    let container = document.getElementById('shareToastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'shareToastContainer';
      container.className = 'position-fixed top-0 end-0 p-3';
      container.style.zIndex = '1100';
      document.body.appendChild(container);
    }

    const colors = {
      success: 'bg-success text-white',
      danger: 'bg-danger text-white',
      warning: 'bg-warning text-dark',
      info: 'bg-info text-dark',
    };

    const toast = document.createElement('div');
    toast.className = `toast show ${colors[type] || 'bg-secondary text-white'}`;
    toast.setAttribute('role', 'alert');
    toast.style.minWidth = '300px';
    toast.innerHTML = `
      <div class="toast-body d-flex align-items-center">
        <span class="flex-grow-1">${message}</span>
        <button type="button" class="btn-close btn-close-white ms-2"
                onclick="this.closest('.toast').remove()"></button>
      </div>
    `;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 6000);
  }

  function _esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
  }

  function getOnlineCount() {
    return onlineUsers.length;
  }

  function isConnected() {
    return connected;
  }

  // ── Public API ──────────────────────────────────────────────────────

  return {
    init,
    openShareModal,
    sendShareRequest,
    cancelShare,
    acceptOffer,
    declineOffer,
    getOnlineCount,
    isConnected,
  };
})();

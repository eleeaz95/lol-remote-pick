/**
 * LoL Remote Pick - Application Controller & Real-Time Engine
 */

(function () {
  'use strict';

  // =========================================================================
  // Application State
  // =========================================================================

  const state = {
    connected: false,
    mock: false,
    phase: 'DISCONNECTED', // 'NONE' | 'LOBBY' | 'IN_QUEUE' | 'READY_CHECK' | 'CHAMP_SELECT' | 'IN_GAME' | 'DISCONNECTED'
    summoner: {
      displayName: '',
      profileIconId: 0,
      summonerLevel: 1
    },
    lobby: {
      queueId: 420,
      queueName: 'Ranked Solo/Duo',
      isLeader: true,
      canStartQueue: true,
      members: []
    },
    queue: {
      inQueue: false,
      timeInQueue: 0,
      estimatedTime: 90,
      queueId: 420
    },
    readyCheck: {
      state: 'None', // 'InProgress' | 'EveryoneReady' | 'StrangerNotReady' | 'None'
      playerResponse: 'None', // 'None' | 'Accepted' | 'Declined'
      timer: 10,
      timerMax: 10,
      numAccepted: 0,
      numDeclined: 0,
      totalPlayers: 10
    },
    champSelect: {
      sessionActive: false,
      cellId: -1,
      isMyTurn: false,
      actionPhase: 'NONE', // 'BAN' | 'PICK' | 'FINALIZING' | 'PLANNING' | 'NONE'
      activeAction: null, // { id, type, championId, completed, isInProgress }
      timer: {
        phase: 'NONE',
        adjustedTimeLeftInPhase: 30,
        totalTimeInPhase: 30
      },
      bans: {
        myTeamBans: [],
        theirTeamBans: []
      },
      myTeam: [],
      theirTeam: [],
      mySelection: {
        spell1Id: 4, // Flash
        spell2Id: 14, // Ignite
        selectedChampionId: 0
      }
    }
  };

  // Local UI State
  const localState = {
    champions: [],
    championsMap: new Map(), // ID -> Champ
    spells: [],
    spellsMap: new Map(), // ID -> Spell
    queues: [],
    selectedChampionId: 0,
    selectedSpellSlot: 1, // 1 for D, 2 for F
    activeRoleFilter: 'ALL',
    searchQuery: '',
    soundEnabled: localStorage.getItem('lol_sound_enabled') !== 'false',
    wakeLock: null,
    ws: null,
    wsConnected: false,
    pollInterval: null,
    reconnectTimeout: null,
    reconnectAttempts: 0,
    badgeDebounceTimeout: null,
    prevPhase: 'DISCONNECTED',
    prevIsMyTurn: false,
    readyCheckClientTimer: null,
    champSelectClientTimer: null,
    queueClientTimer: null,
    lastReadyCheckTick: -1,
    lastCsTick: -1,

    // Monotonic timestamp-anchored timer properties
    csTargetEndMs: 0,
    lastCsActionId: null,
    lastCsPhase: null,
    lastCsDisplayedSec: -1,
    readyCheckTargetEndMs: 0,
    lastReadyCheckState: null,
    lastReadyCheckDisplayedSec: -1,
    queueStartMs: 0,
    lastQueueDisplayedSec: -1
  };
  // Default Fallback Catalogs
  const DEFAULT_SPELLS = [
    { id: 4, name: 'Flash', key: 'SummonerFlash', cooldown: 300, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerFlash.png', desc: 'Teleports your champion a short distance.' },
    { id: 14, name: 'Ignite', key: 'SummonerDot', cooldown: 180, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerDot.png', desc: 'Ignites target enemy champion dealing true damage.' },
    { id: 12, name: 'Teleport', key: 'SummonerTeleport', cooldown: 360, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerTeleport.png', desc: 'Channels to teleport to an allied structure/unit.' },
    { id: 11, name: 'Smite', key: 'SummonerSmite', cooldown: 90, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerSmite.png', desc: 'Deals true damage to monsters and minions.' },
    { id: 7, name: 'Heal', key: 'SummonerHeal', cooldown: 240, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerHeal.png', desc: 'Restores health and grants movement speed to you and target ally.' },
    { id: 21, name: 'Barrier', key: 'SummonerBarrier', cooldown: 180, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerBarrier.png', desc: 'Shields your champion from damage.' },
    { id: 3, name: 'Exhaust', key: 'SummonerExhaust', cooldown: 210, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerExhaust.png', desc: 'Exhausts target enemy champion, reducing damage and speed.' },
    { id: 1, name: 'Cleanse', key: 'SummonerBoost', cooldown: 210, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerBoost.png', desc: 'Removes disables and debuffs.' },
    { id: 6, name: 'Ghost', key: 'SummonerHaste', cooldown: 210, iconUrl: 'https://ddragon.leagueoflegends.com/cdn/14.1.1/img/spell/SummonerHaste.png', desc: 'Grants burst of movement speed and ghosting.' }
  ];

  const POPULAR_CHAMPIONS_FALLBACK = [
    { id: 103, key: 'Ahri', name: 'Ahri', roles: ['MIDDLE', 'MAGE', 'ASSASSIN'] },
    { id: 84, key: 'Akali', name: 'Akali', roles: ['MIDDLE', 'TOP', 'ASSASSIN'] },
    { id: 12, key: 'Alistar', name: 'Alistar', roles: ['UTILITY', 'TANK'] },
    {"id": 799, "key": "Ambessa", "name": "Ambessa", "roles": ["TOP", "FIGHTER"]},
    {"id": 893, "key": "Aurora", "name": "Aurora", "roles": ["MIDDLE", "TOP", "MAGE"]},
    {"id": 200, "key": "Belveth", "name": "Bel'Veth", "roles": ["JUNGLE", "FIGHTER"]},
    {"id": 233, "key": "Briar", "name": "Briar", "roles": ["JUNGLE", "FIGHTER"]},
    { id: 32, key: 'Amumu', name: 'Amumu', roles: ['JUNGLE', 'TANK'] },
    { id: 1, key: 'Annie', name: 'Annie', roles: ['MIDDLE', 'MAGE'] },
    { id: 22, key: 'Ashe', name: 'Ashe', roles: ['BOTTOM', 'MARKSMAN', 'UTILITY'] },
    { id: 268, key: 'Azir', name: 'Azir', roles: ['MIDDLE', 'MAGE'] },
    { id: 432, key: 'Bard', name: 'Bard', roles: ['UTILITY', 'SUPPORT'] },
    { id: 53, key: 'Blitzcrank', name: 'Blitzcrank', roles: ['UTILITY', 'TANK'] },
    { id: 63, key: 'Brand', name: 'Brand', roles: ['UTILITY', 'MIDDLE', 'MAGE'] },
    { id: 201, key: 'Braum', name: 'Braum', roles: ['UTILITY', 'TANK'] },
    { id: 51, key: 'Caitlyn', name: 'Caitlyn', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 164, key: 'Camille', name: 'Camille', roles: ['TOP', 'FIGHTER'] },
    { id: 122, key: 'Darius', name: 'Darius', roles: ['TOP', 'FIGHTER'] },
    { id: 119, key: 'Draven', name: 'Draven', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 245, key: 'Ekko', name: 'Ekko', roles: ['JUNGLE', 'MIDDLE', 'ASSASSIN'] },
    { id: 81, key: 'Ezreal', name: 'Ezreal', roles: ['BOTTOM', 'MIDDLE', 'MARKSMAN'] },
    { id: 114, key: 'Fiora', name: 'Fiora', roles: ['TOP', 'FIGHTER'] },
    { id: 86, key: 'Garen', name: 'Garen', roles: ['TOP', 'FIGHTER', 'TANK'] },
    { id: 104, key: 'Graves', name: 'Graves', roles: ['JUNGLE', 'MARKSMAN'] },
    { id: 39, key: 'Irelia', name: 'Irelia', roles: ['TOP', 'MIDDLE', 'FIGHTER'] },
    {"id": 910, "key": "Hwei", "name": "Hwei", "roles": ["MIDDLE", "SUPPORT", "MAGE"]},
    { id: 40, key: 'Janna', name: 'Janna', roles: ['UTILITY', 'SUPPORT'] },
    { id: 24, key: 'Jax', name: 'Jax', roles: ['TOP', 'JUNGLE', 'FIGHTER'] },
    { id: 202, key: 'Jhin', name: 'Jhin', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 222, key: 'Jinx', name: 'Jinx', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 145, key: 'Kaisa', name: 'Kai\'Sa', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 38, key: 'Kassadin', name: 'Kassadin', roles: ['MIDDLE', 'ASSASSIN'] },
    { id: 55, key: 'Katarina', name: 'Katarina', roles: ['MIDDLE', 'ASSASSIN'] },
    { id: 85, key: 'Kennen', name: 'Kennen', roles: ['TOP', 'MAGE'] },
    {"id": 897, "key": "KSante", "name": "K'Sante", "roles": ["TOP", "TANK"]},
    { id: 121, key: 'Khazix', name: 'Kha\'Zix', roles: ['JUNGLE', 'ASSASSIN'] },
    { id: 64, key: 'LeeSin', name: 'Lee Sin', roles: ['JUNGLE', 'FIGHTER'] },
    { id: 89, key: 'Leona', name: 'Leona', roles: ['UTILITY', 'TANK'] },
    { id: 99, key: 'Lux', name: 'Lux', roles: ['MIDDLE', 'UTILITY', 'MAGE'] },
    { id: 11, key: 'MasterYi', name: 'Master Yi', roles: ['JUNGLE', 'ASSASSIN'] },
    { id: 21, key: 'MissFortune', name: 'Miss Fortune', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 25, key: 'Morgana', name: 'Morgana', roles: ['UTILITY', 'MIDDLE', 'MAGE'] },
    {"id": 800, "key": "Mel", "name": "Mel", "roles": ["MIDDLE", "UTILITY", "MAGE"]},
    {"id": 902, "key": "Milio", "name": "Milio", "roles": ["UTILITY", "SUPPORT"]},
    {"id": 950, "key": "Naafiri", "name": "Naafiri", "roles": ["MIDDLE", "ASSASSIN"]},
    {"id": 895, "key": "Nilah", "name": "Nilah", "roles": ["BOTTOM", "FIGHTER"]},
    { id: 267, key: 'Nami', name: 'Nami', roles: ['UTILITY', 'SUPPORT'] },
    { id: 75, key: 'Nasus', name: 'Nasus', roles: ['TOP', 'FIGHTER', 'TANK'] },
    { id: 111, key: 'Nautilus', name: 'Nautilus', roles: ['UTILITY', 'TANK'] },
    { id: 56, key: 'Nocturne', name: 'Nocturne', roles: ['JUNGLE', 'ASSASSIN'] },
    { id: 61, key: 'Orianna', name: 'Orianna', roles: ['MIDDLE', 'MAGE'] },
    { id: 80, key: 'Pantheon', name: 'Pantheon', roles: ['TOP', 'MIDDLE', 'UTILITY', 'FIGHTER'] },
    { id: 555, key: 'Pyke', name: 'Pyke', roles: ['UTILITY', 'ASSASSIN'] },
    { id: 58, key: 'Renekton', name: 'Renekton', roles: ['TOP', 'FIGHTER'] },
    { id: 92, key: 'Riven', name: 'Riven', roles: ['TOP', 'FIGHTER'] },
    { id: 235, key: 'Senna', name: 'Senna', roles: ['UTILITY', 'BOTTOM', 'MARKSMAN'] },
    { id: 875, key: 'Sett', name: 'Sett', roles: ['TOP', 'FIGHTER'] },
    { id: 98, key: 'Shen', name: 'Shen', roles: ['TOP', 'UTILITY', 'TANK'] },
    { id: 37, key: 'Sona', name: 'Sona', roles: ['UTILITY', 'SUPPORT'] },
    {"id": 888, "key": "Renata", "name": "Renata Glasc", "roles": ["UTILITY", "SUPPORT"]},
    { id: 16, key: 'Soraka', name: 'Soraka', roles: ['UTILITY', 'SUPPORT'] },
    {"id": 901, "key": "Smolder", "name": "Smolder", "roles": ["BOTTOM", "MARKSMAN"]},
    { id: 134, key: 'Syndra', name: 'Syndra', roles: ['MIDDLE', 'MAGE'] },
    { id: 91, key: 'Talon', name: 'Talon', roles: ['MIDDLE', 'JUNGLE', 'ASSASSIN'] },
    { id: 412, key: 'Thresh', name: 'Thresh', roles: ['UTILITY', 'SUPPORT'] },
    { id: 18, key: 'Tristana', name: 'Tristana', roles: ['BOTTOM', 'MIDDLE', 'MARKSMAN'] },
    { id: 23, key: 'Tryndamere', name: 'Tryndamere', roles: ['TOP', 'FIGHTER'] },
    { id: 4, key: 'TwistedFate', name: 'Twisted Fate', roles: ['MIDDLE', 'MAGE'] },
    { id: 67, key: 'Vayne', name: 'Vayne', roles: ['BOTTOM', 'TOP', 'MARKSMAN'] },
    { id: 711, key: 'Vex', name: 'Vex', roles: ['MIDDLE', 'MAGE'] },
    { id: 254, key: 'Vi', name: 'Vi', roles: ['JUNGLE', 'FIGHTER'] },
    { id: 112, key: 'Viktor', name: 'Viktor', roles: ['MIDDLE', 'MAGE'] },
    { id: 8, key: 'Vladimir', name: 'Vladimir', roles: ['MIDDLE', 'TOP', 'MAGE'] },
    { id: 106, key: 'Volibear', name: 'Volibear', roles: ['TOP', 'JUNGLE', 'FIGHTER'] },
    { id: 19, key: 'Warwick', name: 'Warwick', roles: ['JUNGLE', 'TOP', 'FIGHTER'] },
    { id: 498, key: 'Xayah', name: 'Xayah', roles: ['BOTTOM', 'MARKSMAN'] },
    { id: 157, key: 'Yasuo', name: 'Yasuo', roles: ['MIDDLE', 'TOP', 'BOTTOM', 'FIGHTER'] },
    { id: 777, key: 'Yone', name: 'Yone', roles: ['MIDDLE', 'TOP', 'ASSASSIN'] },
    {"id": 804, "key": "Yunara", "name": "Yunara", "roles": ["BOTTOM", "MARKSMAN"]},
    { id: 350, key: 'Yuumi', name: 'Yuumi', roles: ['UTILITY', 'SUPPORT'] },
    { id: 154, key: 'Zac', name: 'Zac', roles: ['JUNGLE', 'TOP', 'TANK'] },
    { id: 238, key: 'Zed', name: 'Zed', roles: ['MIDDLE', 'ASSASSIN'] },
    { id: 142, key: 'Zoe', name: 'Zoe', roles: ['MIDDLE', 'MAGE'] },
    { id: 143, key: 'Zyra', name: 'Zyra', roles: ['UTILITY', 'MIDDLE', 'MAGE'] }
  ];

  // =========================================================================
  // Web Audio API Synthesizer (Zero External Dependencies)
  // =========================================================================

  let audioCtx = null;

  function initAudioContext() {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
  }

  // Cinematic Match Found Gong / Chime Chord
  function playMatchFoundSound() {
    if (!localState.soundEnabled || !audioCtx) return;
    try {
      const now = audioCtx.currentTime;

      // Harmonic Minor / Gong frequencies: D3, A3, D4, F4, A4
      const frequencies = [146.83, 220.00, 293.66, 349.23, 440.00];

      frequencies.forEach((freq, index) => {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        const filter = audioCtx.createBiquadFilter();

        osc.type = index === 0 ? 'sine' : (index % 2 === 0 ? 'triangle' : 'sawtooth');
        osc.frequency.setValueAtTime(freq, now);

        filter.type = 'lowpass';
        filter.frequency.setValueAtTime(800 + index * 300, now);
        filter.frequency.exponentialRampToValueAtTime(200, now + 3.5);

        gain.gain.setValueAtTime(0.001, now);
        gain.gain.linearRampToValueAtTime(0.18 / frequencies.length, now + 0.04);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 3.2);

        osc.connect(filter);
        filter.connect(gain);
        gain.connect(audioCtx.destination);

        osc.start(now);
        osc.stop(now + 3.5);
      });
    } catch (e) {
      console.warn('Audio play failed:', e);
    }
  }

  // Your Turn Urgency Alert Fanfare
  function playYourTurnSound() {
    if (!localState.soundEnabled || !audioCtx) return;
    try {
      const now = audioCtx.currentTime;
      const notes = [587.33, 880.00, 1174.66]; // D5, A5, D6

      notes.forEach((freq, i) => {
        const noteStart = now + i * 0.12;
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();

        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, noteStart);

        gain.gain.setValueAtTime(0.001, noteStart);
        gain.gain.linearRampToValueAtTime(0.2, noteStart + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.001, noteStart + 0.45);

        osc.connect(gain);
        gain.connect(audioCtx.destination);

        osc.start(noteStart);
        osc.stop(noteStart + 0.5);
      });
    } catch (e) {
      console.warn('Audio play failed:', e);
    }
  }

  // Lock-In Metallic Anvil / Confirmation Snap
  function playLockInSound() {
    if (!localState.soundEnabled || !audioCtx) return;
    try {
      const now = audioCtx.currentTime;

      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      const filter = audioCtx.createBiquadFilter();

      osc.type = 'triangle';
      osc.frequency.setValueAtTime(1200, now);
      osc.frequency.exponentialRampToValueAtTime(220, now + 0.25);

      filter.type = 'bandpass';
      filter.frequency.setValueAtTime(1400, now);
      filter.Q.setValueAtTime(3, now);

      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.3, now + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);

      osc.connect(filter);
      filter.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.4);
    } catch (e) {
      console.warn('Audio play failed:', e);
    }
  }

  // Countdown Tick (Last 5 Seconds)
  function playTickSound() {
    if (!localState.soundEnabled || !audioCtx) return;
    try {
      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(1760, now); // A6

      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.12, now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.08);

      osc.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.1);
    } catch (e) {
      console.warn('Audio play failed:', e);
    }
  }

  // Subtle Click
  function playClickSound() {
    if (!localState.soundEnabled || !audioCtx) return;
    try {
      const now = audioCtx.currentTime;
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(800, now);

      gain.gain.setValueAtTime(0.001, now);
      gain.gain.linearRampToValueAtTime(0.05, now + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.04);

      osc.connect(gain);
      gain.connect(audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.05);
    } catch (e) {
      // Ignored
    }
  }

  // =========================================================================
  // Vibration API
  // =========================================================================

  function triggerVibrate(pattern) {
    if ('vibrate' in navigator && localState.soundEnabled) {
      try {
        navigator.vibrate(pattern);
      } catch (e) {
        // Ignored
      }
    }
  }

  // =========================================================================
  // Screen Wake Lock API
  // =========================================================================

  async function requestWakeLock() {
    if ('wakeLock' in navigator) {
      try {
        localState.wakeLock = await navigator.wakeLock.request('screen');
        updateWakeLockUI(true);
        localState.wakeLock.addEventListener('release', () => {
          updateWakeLockUI(false);
        });
      } catch (err) {
        console.warn('Wake Lock request failed:', err);
        updateWakeLockUI(false);
      }
    }
  }

  function releaseWakeLock() {
    if (localState.wakeLock) {
      localState.wakeLock.release().catch(() => {});
      localState.wakeLock = null;
      updateWakeLockUI(false);
    }
  }

  function updateWakeLockUI(active) {
    const btn = document.getElementById('btn-wakelock');
    if (btn) {
      if (active) {
        btn.classList.add('active');
        btn.title = 'Screen Wake Lock: Active';
      } else {
        btn.classList.remove('active');
        btn.title = 'Screen Wake Lock: Inactive';
      }
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.connected && (state.phase === 'IN_QUEUE' || state.phase === 'CHAMP_SELECT' || state.phase === 'READY_CHECK')) {
      requestWakeLock();
    }
  });

  // =========================================================================
  // Toast Notifications
  // =========================================================================

  function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.transition = 'all 0.3s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-10px)';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // =========================================================================
  // Catalogs & Assets Indexing
  // =========================================================================

  function getChampionIconUrl(champKey, champId) {
    if (champId && localState.championsMap.has(Number(champId))) {
      const c = localState.championsMap.get(Number(champId));
      if (c && c.icon) return c.icon;
    }
    if (!champKey) return '';
    return `https://ddragon.leagueoflegends.com/cdn/14.24.1/img/champion/${champKey}.png`;
  }

  function getSummonerIconUrl(iconId) {
    if (!iconId) iconId = 29;
    return `https://ddragon.leagueoflegends.com/cdn/14.24.1/img/profileicon/${iconId}.png`;
  }

  function getSpellIconUrl(spell) {
    if (spell && spell.icon) return spell.icon;
    if (spell && spell.iconUrl) return spell.iconUrl;
    if (spell && spell.key) return `https://ddragon.leagueoflegends.com/cdn/14.24.1/img/spell/${spell.key}.png`;
    return '';
  }

  async function loadCatalogs() {
    // 1. Spells
    try {
      const res = await fetch('/api/spells');
      if (res.ok) {
        const data = await res.json();
        localState.spells = Array.isArray(data) ? data : DEFAULT_SPELLS;
      } else {
        localState.spells = DEFAULT_SPELLS;
      }
    } catch (e) {
      localState.spells = DEFAULT_SPELLS;
    }

    localState.spellsMap.clear();
    localState.spells.forEach(s => localState.spellsMap.set(Number(s.id), s));

    // 2. Champions
    try {
      const res = await fetch('/api/champions');
      if (res.ok) {
        const data = await res.json();
        const champList = Array.isArray(data) ? data : (data.champions || POPULAR_CHAMPIONS_FALLBACK);
        localState.champions = champList.map(c => ({
          id: Number(c.id),
          key: c.key || c.name || String(c.id),
          name: c.name || c.key || 'Champion',
          icon: c.icon || getChampionIconUrl(c.key || c.name, c.id),
          roles: Array.isArray(c.roles) ? c.roles.map(r => r.toUpperCase()) : ['MIDDLE']
        }));
      } else {
        localState.champions = POPULAR_CHAMPIONS_FALLBACK;
      }
    } catch (e) {
      localState.champions = POPULAR_CHAMPIONS_FALLBACK;
    }

    // Sort champions alphabetically
    localState.champions.sort((a, b) => a.name.localeCompare(b.name));
    localState.championsMap.clear();
    localState.champions.forEach(c => localState.championsMap.set(c.id, c));

    // Render champion grid & spell modal
    renderChampionsGrid();
    renderSpellsModal();
  }

  // =========================================================================
  // WebSocket & REST API Communication
  // =========================================================================

  function connectWebSocket() {
    if (localState.ws) {
      try { localState.ws.close(); } catch (e) {}
      localState.ws = null;
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8000';
    const wsUrl = `${proto}//${host}/ws`;

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        localState.wsConnected = true;
        localState.reconnectAttempts = 0;
        updateConnectionBadge(true, state.mock);
        requestWakeLock();
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          handleServerMessage(message);
        } catch (e) {
          console.warn('Malformed WS message:', e);
        }
      };

      ws.onclose = () => {
        localState.wsConnected = false;
        scheduleReconnect();
      };

      ws.onerror = () => {
        localState.wsConnected = false;
      };

      localState.ws = ws;
    } catch (err) {
      console.warn('WS Init Error:', err);
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (localState.reconnectTimeout) return;
    localState.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(1.5, localState.reconnectAttempts - 1), 8000);

    updateConnectionBadge(false, false, true);

    localState.reconnectTimeout = setTimeout(() => {
      localState.reconnectTimeout = null;
      connectWebSocket();
      fetchStateREST();
    }, delay);
  }

  async function fetchStateREST() {
    try {
      const res = await fetch('/api/state');
      if (res.ok) {
        const data = await res.json();
        handleServerMessage(data);
      }
    } catch (e) {
      // Ignored during disconnected states
    }
  }

  async function sendApiRequest(endpoint, body = {}) {
    // 1. Prefer WebSocket when connected and healthy (eliminates dual-transport race conditions)
    if (localState.ws && localState.wsConnected && localState.ws.readyState === WebSocket.OPEN) {
      try {
        localState.ws.send(JSON.stringify({ endpoint, ...body }));
        return true;
      } catch (e) {
        console.warn('WS send failed, falling back to REST:', e);
      }
    }

    // 2. Fallback to REST POST only if WebSocket is unavailable or send failed
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || err.message || 'Action failed', 'error');
        return false;
      }
      return true;
    } catch (e) {
      showToast('Network error performing action', 'error');
      return false;
    }
  }

  // =========================================================================
  // State Normalization & Transition Handling
  // =========================================================================

  function handleServerMessage(data) {
    if (!data) return;

    // Direct state payload or wrapped
    const payload = data.type === 'state' ? data.payload : (data.state || data);

    // Merge connection flags
    state.connected = payload.connected !== undefined ? Boolean(payload.connected) : state.connected;
    state.mock = Boolean(payload.mock);

    // Phase normalization
    let nextPhase = (payload.phase || 'DISCONNECTED').toUpperCase();
    if (!state.connected && nextPhase !== 'NONE' && nextPhase !== 'LOBBY' && nextPhase !== 'IN_QUEUE' && nextPhase !== 'READY_CHECK' && nextPhase !== 'CHAMP_SELECT' && nextPhase !== 'IN_GAME') {
      nextPhase = 'DISCONNECTED';
    }
    state.phase = nextPhase;

    // Summoner Profile
    if (payload.summoner) {
      state.summoner = {
        displayName: payload.summoner.displayName || payload.summoner.gameName || 'Summoner',
        profileIconId: payload.summoner.profileIconId || 29,
        summonerLevel: payload.summoner.summonerLevel || 1
      };
    }

    // Lobby
    if (payload.lobby) {
      state.lobby = {
        queueId: payload.lobby.queueId || 420,
        queueName: payload.lobby.queueName || 'Ranked Solo/Duo',
        isLeader: payload.lobby.isLeader !== undefined ? payload.lobby.isLeader : true,
        canStartQueue: payload.lobby.canStartQueue !== undefined ? payload.lobby.canStartQueue : true,
        members: Array.isArray(payload.lobby.members) ? payload.lobby.members : []
      };
    }

    // Queue
    if (payload.queue) {
      state.queue = {
        inQueue: Boolean(payload.queue.inQueue),
        timeInQueue: payload.queue.timeInQueue || 0,
        estimatedTime: payload.queue.estimatedTime || 90,
        queueId: payload.queue.queueId || state.lobby.queueId
      };

      if (state.phase === 'IN_QUEUE' && state.queue.inQueue) {
        const serverElapsedMs = (state.queue.timeInQueue || 0) * 1000;
        if (!localState.queueStartMs) {
          localState.queueStartMs = Date.now() - serverElapsedMs;
        } else {
          const currentLocalElapsedMs = Date.now() - localState.queueStartMs;
          if (Math.abs(currentLocalElapsedMs - serverElapsedMs) > 5000 && serverElapsedMs > 0) {
            localState.queueStartMs = Date.now() - serverElapsedMs;
          }
        }
      } else {
        localState.queueStartMs = 0;
        localState.lastQueueDisplayedSec = -1;
      }
    } else if (state.phase !== 'IN_QUEUE') {
      localState.queueStartMs = 0;
      localState.lastQueueDisplayedSec = -1;
    }

    // Ready Check
    if (payload.readyCheck) {
      state.readyCheck = {
        state: payload.readyCheck.state || 'None',
        playerResponse: payload.readyCheck.playerResponse || 'None',
        timer: payload.readyCheck.timer !== undefined ? payload.readyCheck.timer : 10,
        timerMax: payload.readyCheck.timerMax || 10,
        numAccepted: payload.readyCheck.numAccepted || 0,
        numDeclined: payload.readyCheck.numDeclined || 0,
        totalPlayers: payload.readyCheck.totalPlayers || 10
      };

      if (state.phase === 'READY_CHECK' && state.readyCheck.state === 'InProgress') {
        const serverLeftMs = (state.readyCheck.timer !== undefined ? state.readyCheck.timer : 10) * 1000;
        const newTargetEndMs = Date.now() + serverLeftMs;

        if (!localState.readyCheckTargetEndMs || localState.lastReadyCheckState !== 'InProgress') {
          localState.readyCheckTargetEndMs = newTargetEndMs;
        } else {
          const currentRemainingMs = Math.max(0, localState.readyCheckTargetEndMs - Date.now());
          const drift = Math.abs(currentRemainingMs - serverLeftMs);
          if (drift > 2000) {
            localState.readyCheckTargetEndMs = newTargetEndMs;
          }
        }
        localState.lastReadyCheckState = 'InProgress';
      } else {
        localState.readyCheckTargetEndMs = 0;
        localState.lastReadyCheckState = state.readyCheck.state;
        localState.lastReadyCheckDisplayedSec = -1;
      }
    } else if (state.phase !== 'READY_CHECK') {
      localState.readyCheckTargetEndMs = 0;
      localState.lastReadyCheckState = null;
      localState.lastReadyCheckDisplayedSec = -1;
    }

    // Champ Select
    if (payload.champSelect) {
      const cs = payload.champSelect;
      state.champSelect = {
        sessionActive: Boolean(cs.sessionActive),
        cellId: cs.cellId !== undefined ? cs.cellId : -1,
        isMyTurn: Boolean(cs.isMyTurn),
        actionPhase: (cs.actionPhase || 'NONE').toUpperCase(),
        activeAction: cs.activeAction || null,
        localPickActionId: cs.localPickActionId || null,
        localBanActionId: cs.localBanActionId || null,
        myPickIntent: cs.myPickIntent || 0,
        timer: {
          phase: cs.timer?.phase || 'NONE',
          adjustedTimeLeftInPhase: cs.timer?.adjustedTimeLeftInPhase !== undefined ? cs.timer.adjustedTimeLeftInPhase : 30,
          totalTimeInPhase: cs.timer?.totalTimeInPhase !== undefined ? cs.timer.totalTimeInPhase : 30
        },
        bans: {
          myTeamBans: cs.bans?.myTeamBans || [],
          theirTeamBans: cs.bans?.theirTeamBans || []
        },
        myTeam: Array.isArray(cs.myTeam) ? cs.myTeam : [],
        theirTeam: Array.isArray(cs.theirTeam) ? cs.theirTeam : [],
        mySelection: {
          spell1Id: cs.mySelection?.spell1Id || 4,
          spell2Id: cs.mySelection?.spell2Id || 14,
          selectedChampionId: cs.mySelection?.selectedChampionId || 0
        }
      };

      if (state.phase === 'CHAMP_SELECT' && state.champSelect.sessionActive) {
        const currentActionId = cs.activeAction ? cs.activeAction.id : null;
        const currentPhase = state.champSelect.actionPhase;
        const serverLeftMs = (state.champSelect.timer.adjustedTimeLeftInPhase || 0) * 1000;
        const newTargetEndMs = Date.now() + serverLeftMs;

        if (
          !localState.csTargetEndMs ||
          currentActionId !== localState.lastCsActionId ||
          currentPhase !== localState.lastCsPhase
        ) {
          localState.csTargetEndMs = newTargetEndMs;
        } else {
          const currentRemainingMs = Math.max(0, localState.csTargetEndMs - Date.now());
          const drift = Math.abs(currentRemainingMs - serverLeftMs);
          if (drift > 2000) {
            localState.csTargetEndMs = newTargetEndMs;
          }
        }

        localState.lastCsActionId = currentActionId;
        localState.lastCsPhase = currentPhase;
      } else {
        localState.csTargetEndMs = 0;
        localState.lastCsActionId = null;
        localState.lastCsPhase = null;
        localState.lastCsDisplayedSec = -1;
      }

      // Adopt server pick intent if local selection not yet made
      if (!localState.selectedChampionId && (cs.myPickIntent || cs.mySelection?.selectedChampionId)) {
        localState.selectedChampionId = cs.myPickIntent || cs.mySelection.selectedChampionId;
      }
    } else if (state.phase !== 'CHAMP_SELECT') {
      localState.csTargetEndMs = 0;
      localState.lastCsActionId = null;
      localState.lastCsPhase = null;
      localState.lastCsDisplayedSec = -1;
    }

    // Process State Transitions & Audio/Vibration Triggers
    handlePhaseTransitions();

    // Render Full UI
    renderApp();
  }

  function handlePhaseTransitions() {
    const currPhase = state.phase;
    const prevPhase = localState.prevPhase;

    // 1. Entering Ready Check (Match Found!)
    if (currPhase === 'READY_CHECK' && prevPhase !== 'READY_CHECK') {
      playMatchFoundSound();
      triggerVibrate([300, 100, 300, 100, 500]);
      requestWakeLock();
    }

    // 2. Entering Champ Select
    if (currPhase === 'CHAMP_SELECT' && prevPhase !== 'CHAMP_SELECT') {
      requestWakeLock();
    }

    // 3. Your Turn in Champ Select
    if (currPhase === 'CHAMP_SELECT') {
      if (state.champSelect.isMyTurn && !localState.prevIsMyTurn) {
        playYourTurnSound();
        triggerVibrate([200, 100, 200]);
      }
    }

    localState.prevPhase = currPhase;
    localState.prevIsMyTurn = state.champSelect.isMyTurn;
  }

  // =========================================================================
  // Smooth Local Timers Engine (50ms interval)
  // =========================================================================

  function startTimerEngine() {
    setInterval(() => {
      // In-Queue Timer
      if (state.phase === 'IN_QUEUE') {
        updateQueueTimerDisplay();
      }

      // Ready Check Countdown
      if (state.phase === 'READY_CHECK' && state.readyCheck.state === 'InProgress') {
        updateReadyCheckTimerDisplay();
      }

      // Champ Select Countdown
      if (state.phase === 'CHAMP_SELECT' && state.champSelect.sessionActive) {
        updateChampSelectTimerDisplay();
      }
    }, 50);
  }

  // =========================================================================
  // UI Rendering & DOM Updates
  // =========================================================================

  function updateConnectionBadge(connected, isMock, isReconnecting = false) {
    const badge = document.getElementById('connection-badge');
    const text = document.getElementById('connection-text');
    if (!badge || !text) return;

    const applyBadgeState = (isConn, mock, reconn) => {
      badge.className = 'connection-badge';
      if (reconn) {
        badge.classList.add('reconnecting');
        text.textContent = 'Reconnecting...';
      } else if (mock) {
        badge.classList.add('mock');
        text.textContent = 'Mock Mode';
      } else if (isConn) {
        badge.classList.add('connected');
        text.textContent = 'LCU Connected';
      } else {
        badge.classList.add('disconnected');
        text.textContent = 'Disconnected';
      }
    };

    if (connected || isMock) {
      if (localState.badgeDebounceTimeout) {
        clearTimeout(localState.badgeDebounceTimeout);
        localState.badgeDebounceTimeout = null;
      }
      applyBadgeState(connected, isMock, isReconnecting);
    } else {
      // Debounce disconnected/reconnecting state by 1.5s to filter transient network jitters
      if (!localState.badgeDebounceTimeout) {
        localState.badgeDebounceTimeout = setTimeout(() => {
          localState.badgeDebounceTimeout = null;
          applyBadgeState(false, false, isReconnecting);
        }, 1500);
      }
    }
  }

  function renderApp() {
    updateConnectionBadge(state.connected, state.mock, !localState.wsConnected && state.connected);

    // Profile Bar
    const profileContainer = document.getElementById('profile-container');
    const userAvatar = document.getElementById('user-avatar');
    const userLevel = document.getElementById('user-level');
    const userName = document.getElementById('user-name');

    if (state.summoner && state.summoner.displayName) {
      profileContainer.classList.remove('hidden');
      userName.textContent = state.summoner.displayName;
      userLevel.textContent = state.summoner.summonerLevel;
      userAvatar.src = getSummonerIconUrl(state.summoner.profileIconId);
    } else {
      profileContainer.classList.add('hidden');
    }

    // Switch View Panels
    switchView(state.phase);

    // Render individual view content
    switch (state.phase) {
      case 'LOBBY':
      case 'NONE':
        renderLobbyView();
        break;
      case 'IN_QUEUE':
        renderInQueueView();
        break;
      case 'READY_CHECK':
        renderReadyCheckView();
        break;
      case 'CHAMP_SELECT':
        renderChampSelectView();
        break;
      case 'IN_GAME':
        renderInGameView();
        break;
      case 'DISCONNECTED':
      default:
        renderDisconnectedView();
        break;
    }
  }

  function switchView(targetPhase) {
    const viewMap = {
      'DISCONNECTED': 'view-disconnected',
      'NONE': 'view-lobby',
      'LOBBY': 'view-lobby',
      'IN_QUEUE': 'view-in-queue',
      'READY_CHECK': 'view-ready-check',
      'CHAMP_SELECT': 'view-champ-select',
      'IN_GAME': 'view-in-game'
    };

    const targetId = viewMap[targetPhase] || 'view-disconnected';

    document.querySelectorAll('.view-panel').forEach(panel => {
      if (panel.id === targetId) {
        panel.classList.add('active');
        panel.classList.remove('hidden');
      } else {
        panel.classList.remove('active');
        panel.classList.add('hidden');
      }
    });
  }

  // 1. Disconnected View
  function renderDisconnectedView() {
    const statusText = document.getElementById('reconnect-status');
    if (statusText) {
      statusText.textContent = localState.wsConnected ? 'Connected to server, waiting for client...' : 'Attempting to reach backend...';
    }
  }

  // 2. Lobby View
  function renderLobbyView() {
    const queueBadge = document.getElementById('current-queue-badge');
    if (queueBadge) {
      queueBadge.textContent = state.lobby.queueName || 'Ranked Solo/Duo';
    }

    // Queue button active state
    document.querySelectorAll('.queue-btn').forEach(btn => {
      const qId = Number(btn.getAttribute('data-queue-id'));
      if (qId === state.lobby.queueId) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Members list
    const membersList = document.getElementById('lobby-members-list');
    const membersCount = document.getElementById('members-count');
    if (membersList) {
      membersList.innerHTML = '';
      const members = state.lobby.members.length > 0 ? state.lobby.members : [
        {
          summonerName: state.summoner.displayName || 'You',
          profileIconId: state.summoner.profileIconId || 29,
          isLeader: true,
          firstPositionPreference: document.getElementById('select-role-primary')?.value || 'MIDDLE',
          secondPositionPreference: document.getElementById('select-role-secondary')?.value || 'BOTTOM'
        }
      ];

      if (membersCount) membersCount.textContent = `${members.length} / 5`;

      members.forEach(m => {
        const row = document.createElement('div');
        row.className = 'member-row';
        row.innerHTML = `
          <div class="member-left">
            <img class="member-avatar" src="${getSummonerIconUrl(m.profileIconId)}" alt="Avatar">
            <span class="member-name">${escapeHtml(m.summonerName || 'Summoner')}</span>
            ${m.isLeader ? '<span class="member-leader-crown" title="Party Leader">👑</span>' : ''}
          </div>
          <div class="member-roles">
            <span>${escapeHtml(m.firstPositionPreference || 'FILL')} / ${escapeHtml(m.secondPositionPreference || 'FILL')}</span>
          </div>
        `;
        membersList.appendChild(row);
      });
    }

    // Buttons
    const btnStart = document.getElementById('btn-start-queue');
    const btnCreate = document.getElementById('btn-create-lobby');
    if (state.phase === 'NONE') {
      btnStart.classList.add('hidden');
      btnCreate.classList.remove('hidden');
    } else {
      btnStart.classList.remove('hidden');
      btnCreate.classList.add('hidden');
      btnStart.disabled = !state.lobby.canStartQueue;
      btnStart.querySelector('.btn-text').textContent = state.lobby.isLeader ? 'START QUEUE' : 'WAITING FOR LEADER';
    }
  }

  // 3. In-Queue View
  function renderInQueueView() {
    const queueName = document.getElementById('queue-current-name');
    if (queueName) queueName.textContent = state.lobby.queueName || 'Ranked Solo/Duo';

    const pRole = document.getElementById('select-role-primary')?.value || 'MID';
    const sRole = document.getElementById('select-role-secondary')?.value || 'BOT';
    const pBadge = document.getElementById('queue-pos-primary');
    const sBadge = document.getElementById('queue-pos-secondary');
    if (pBadge) pBadge.textContent = pRole.substring(0, 3);
    if (sBadge) sBadge.textContent = sRole.substring(0, 3);

    updateQueueTimerDisplay();
  }

  function updateQueueTimerDisplay() {
    const elapsedEl = document.getElementById('queue-time-elapsed');
    const estEl = document.getElementById('queue-time-estimated');

    if (!localState.queueStartMs) {
      const serverElapsed = state.queue.timeInQueue || 0;
      localState.queueStartMs = Date.now() - (serverElapsed * 1000);
    }

    const elapsedMs = Math.max(0, Date.now() - localState.queueStartMs);
    const elapsedSec = Math.floor(elapsedMs / 1000);

    if (elapsedEl) {
      if (localState.lastQueueDisplayedSec !== elapsedSec) {
        localState.lastQueueDisplayedSec = elapsedSec;
        elapsedEl.textContent = formatTimeSeconds(elapsedSec);
      }
    }
    if (estEl) {
      estEl.textContent = `Estimated ${formatTimeSeconds(state.queue.estimatedTime)}`;
    }
  }

  // 4. Ready Check (Match Found) View
  function renderReadyCheckView() {
    updateReadyCheckTimerDisplay();

    // Accepted count text
    const acceptedCountText = document.getElementById('ready-accepted-count');
    if (acceptedCountText) {
      acceptedCountText.textContent = `${state.readyCheck.numAccepted} / ${state.readyCheck.totalPlayers} ACCEPTED`;
    }

    // Player status dots
    const dotsContainer = document.getElementById('ready-player-dots');
    if (dotsContainer) {
      dotsContainer.innerHTML = '';
      for (let i = 0; i < state.readyCheck.totalPlayers; i++) {
        const dot = document.createElement('div');
        dot.className = 'player-dot';
        if (i < state.readyCheck.numAccepted) {
          dot.classList.add('accepted');
        } else if (i < state.readyCheck.numAccepted + state.readyCheck.numDeclined) {
          dot.classList.add('declined');
        }
        dotsContainer.appendChild(dot);
      }
    }

    // Response state buttons
    const btnAccept = document.getElementById('btn-ready-accept');
    const btnDecline = document.getElementById('btn-ready-decline');
    const responseBadge = document.getElementById('ready-response-badge');

    if (state.readyCheck.playerResponse === 'Accepted') {
      btnAccept.classList.add('hidden');
      btnDecline.classList.add('hidden');
      responseBadge.classList.remove('hidden');
      responseBadge.innerHTML = '<span>YOU ACCEPTED! WAITING...</span>';
    } else if (state.readyCheck.playerResponse === 'Declined') {
      btnAccept.classList.add('hidden');
      btnDecline.classList.add('hidden');
      responseBadge.classList.remove('hidden');
      responseBadge.innerHTML = '<span style="color: var(--danger-red);">MATCH DECLINED</span>';
    } else {
      btnAccept.classList.remove('hidden');
      btnDecline.classList.remove('hidden');
      responseBadge.classList.add('hidden');
    }
  }

  function updateReadyCheckTimerDisplay() {
    const timerText = document.getElementById('ready-seconds-left');
    const progressFill = document.getElementById('ready-progress-fill');

    if (!localState.readyCheckTargetEndMs) {
      const serverLeft = state.readyCheck.timer !== undefined ? state.readyCheck.timer : 10;
      localState.readyCheckTargetEndMs = Date.now() + (serverLeft * 1000);
    }

    const remainingMs = Math.max(0, localState.readyCheckTargetEndMs - Date.now());
    const remainingSecFloat = remainingMs / 1000;
    const seconds = Math.max(0, Math.ceil(remainingSecFloat));

    if (seconds <= 5 && seconds > 0 && seconds !== localState.lastReadyCheckTick) {
      localState.lastReadyCheckTick = seconds;
      playTickSound();
    }

    if (timerText) {
      if (localState.lastReadyCheckDisplayedSec !== seconds) {
        localState.lastReadyCheckDisplayedSec = seconds;
        timerText.textContent = seconds;
      }
    }

    if (progressFill) {
      const total = state.readyCheck.timerMax || 10;
      const pct = Math.max(0, Math.min(100, (remainingSecFloat / total) * 100));
      progressFill.style.width = `${pct}%`;
    }
  }

  // 5. Champ Select View
  function renderChampSelectView() {
    const cs = state.champSelect;

    // Phase Title & Timer
    const phaseTitle = document.getElementById('cs-phase-title');
    if (phaseTitle) {
      phaseTitle.textContent = `${cs.actionPhase} PHASE`;
      if (cs.actionPhase === 'BAN') {
        phaseTitle.classList.add('ban-phase');
      } else {
        phaseTitle.classList.remove('ban-phase');
      }
    }

    // Turn Flasher Banner
    const turnBanner = document.getElementById('cs-turn-banner');
    const turnText = document.getElementById('cs-turn-text');
    if (turnBanner && turnText) {
      if (cs.isMyTurn) {
        turnBanner.classList.remove('hidden');
        turnText.textContent = cs.actionPhase === 'BAN' ? 'YOUR TURN TO BAN!' : 'YOUR TURN TO PICK!';
      } else {
        turnBanner.classList.add('hidden');
      }
    }

    updateChampSelectTimerDisplay();

    // Rosters & Bans
    renderTeamRosters();

    // Spells Pickers Buttons
    const spell1Icon = document.getElementById('spell-1-icon');
    const spell2Icon = document.getElementById('spell-2-icon');
    const s1 = localState.spellsMap.get(cs.mySelection.spell1Id);
    const s2 = localState.spellsMap.get(cs.mySelection.spell2Id);
    if (spell1Icon && s1) spell1Icon.src = getSpellIconUrl(s1);
    if (spell2Icon && s2) spell2Icon.src = getSpellIconUrl(s2);

    // Selected Champ Preview & Action Button
    renderChampSelectActionBar();
  }

  function updateChampSelectTimerDisplay() {
    const cs = state.champSelect;
    const timerValue = document.getElementById('cs-timer-value');
    const timerFill = document.getElementById('cs-timer-fill');

    if (!localState.csTargetEndMs) {
      const serverLeft = cs.timer?.adjustedTimeLeftInPhase !== undefined ? cs.timer.adjustedTimeLeftInPhase : 30;
      localState.csTargetEndMs = Date.now() + (serverLeft * 1000);
    }

    const remainingMs = Math.max(0, localState.csTargetEndMs - Date.now());
    const remainingSecFloat = remainingMs / 1000;
    const seconds = Math.max(0, Math.ceil(remainingSecFloat));

    if (cs.isMyTurn && seconds <= 5 && seconds > 0 && seconds !== localState.lastCsTick) {
      localState.lastCsTick = seconds;
      playTickSound();
    }

    if (timerValue) {
      if (localState.lastCsDisplayedSec !== seconds) {
        localState.lastCsDisplayedSec = seconds;
        timerValue.textContent = seconds;
        if (seconds <= 8) {
          timerValue.classList.add('urgent');
        } else {
          timerValue.classList.remove('urgent');
        }
      }
    }

    if (timerFill) {
      const total = cs.timer?.totalTimeInPhase || 30;
      const pct = Math.max(0, Math.min(100, (remainingSecFloat / total) * 100));
      timerFill.style.width = `${pct}%`;
      if (seconds <= 8) {
        timerFill.classList.add('urgent');
      } else {
        timerFill.classList.remove('urgent');
      }
    }
  }

  function renderTeamRosters() {
    const cs = state.champSelect;
    const allyRoster = document.getElementById('cs-ally-roster');
    const enemyRoster = document.getElementById('cs-enemy-roster');
    const allyBansEl = document.getElementById('cs-ally-bans');
    const enemyBansEl = document.getElementById('cs-enemy-bans');

    // Ally Team
    if (allyRoster) {
      allyRoster.innerHTML = '';
      cs.myTeam.forEach(member => {
        const champId = member.displayedChampionId || member.championId || member.championPickIntent;
        const champ = localState.championsMap.get(champId);
        const s1 = localState.spellsMap.get(member.spell1Id);
        const s2 = localState.spellsMap.get(member.spell2Id);
        const isMe = member.isLocalPlayer || member.cellId === cs.cellId;
        const isIntent = member.isPickIntent || (!member.isLocked && Boolean(member.championPickIntent > 0));

        const slot = document.createElement('div');
        slot.className = `player-slot-card ${isMe ? 'is-me' : ''} ${isIntent ? 'is-intent' : ''}`;
        slot.innerHTML = `
          ${champ ? `<img class="slot-champ-img" src="${getChampionIconUrl(champ.key)}" alt="${escapeHtml(champ.name)}">` : ''}
          ${isIntent ? `<span class="slot-intent-tag">HOVER</span>` : ''}
          <span class="slot-role-tag">${escapeHtml((member.assignedPosition || '').substring(0, 3))}</span>
          <div class="slot-spells-mini">
            ${s1 ? `<img class="spell-mini-img" src="${getSpellIconUrl(s1)}">` : ''}
            ${s2 ? `<img class="spell-mini-img" src="${getSpellIconUrl(s2)}">` : ''}
          </div>
        `;
        allyRoster.appendChild(slot);
      });
    }

    // Enemy Team
    if (enemyRoster) {
      enemyRoster.innerHTML = '';
      cs.theirTeam.forEach(enemy => {
        const champ = localState.championsMap.get(enemy.championId);
        const slot = document.createElement('div');
        slot.className = 'player-slot-card';
        slot.innerHTML = `
          ${champ ? `<img class="slot-champ-img" src="${getChampionIconUrl(champ.key)}" alt="${escapeHtml(champ.name)}">` : ''}
          <span class="slot-role-tag">${escapeHtml((enemy.assignedPosition || '').substring(0, 3))}</span>
        `;
        enemyRoster.appendChild(slot);
      });
    }

    // Bans
    if (allyBansEl) {
      allyBansEl.innerHTML = '';
      cs.bans.myTeamBans.forEach(bId => {
        const champ = localState.championsMap.get(bId);
        const b = document.createElement('div');
        b.className = 'ban-slot-mini';
        b.innerHTML = champ ? `<img class="ban-champ-img" src="${getChampionIconUrl(champ.key)}"><div class="ban-slash"></div>` : '<div class="ban-slash"></div>';
        allyBansEl.appendChild(b);
      });
    }

    if (enemyBansEl) {
      enemyBansEl.innerHTML = '';
      cs.bans.theirTeamBans.forEach(bId => {
        const champ = localState.championsMap.get(bId);
        const b = document.createElement('div');
        b.className = 'ban-slot-mini';
        b.innerHTML = champ ? `<img class="ban-champ-img" src="${getChampionIconUrl(champ.key)}"><div class="ban-slash"></div>` : '<div class="ban-slash"></div>';
        enemyBansEl.appendChild(b);
      });
    }
  }

  function renderChampSelectActionBar() {
    const cs = state.champSelect;
    const selectedId = localState.selectedChampionId || cs.myPickIntent || cs.mySelection.selectedChampionId;
    const champ = localState.championsMap.get(selectedId);

    const previewIcon = document.getElementById('cs-preview-icon');
    const previewName = document.getElementById('cs-preview-name');
    const previewSub = document.getElementById('cs-preview-sub');
    const btnAction = document.getElementById('btn-cs-action');
    const btnActionText = document.getElementById('cs-action-btn-text');

    if (champ) {
      previewIcon.src = getChampionIconUrl(champ.key);
      previewName.textContent = champ.name;
    } else {
      previewIcon.src = '';
      previewName.textContent = 'Select Champion';
      previewSub.textContent = 'Tap a champion above';
    }

    if (!btnAction) return;

    if (cs.actionPhase === 'BAN' && cs.isMyTurn) {
      // Active Ban turn
      previewSub.textContent = 'Ready to ban';
      btnAction.className = 'btn btn-lockin ban-action';
      btnActionText.textContent = champ ? `BAN ${champ.name.toUpperCase()}` : 'BAN';
      btnAction.disabled = !champ;
    } else if (cs.actionPhase === 'PICK' && cs.isMyTurn) {
      // Active Pick turn
      previewSub.textContent = 'Ready to lock in';
      btnAction.className = 'btn btn-gold btn-lockin';
      btnActionText.textContent = champ ? `LOCK IN ${champ.name.toUpperCase()}` : 'LOCK IN';
      btnAction.disabled = !champ;
    } else {
      // Pre-selection / Pick intent mode (before turn, after ban, or planning)
      previewSub.textContent = champ ? 'Pre-selected (Pick Intent)' : 'Pre-select your champion';
      btnAction.className = 'btn btn-lockin preselect-action';
      btnActionText.textContent = champ ? `PRE-SELECT ${champ.name.toUpperCase()}` : 'PRE-SELECT';
      btnAction.disabled = !champ;
    }
  }

  // Champion Grid & Search Rendering
  function renderChampionsGrid() {
    const grid = document.getElementById('champions-grid');
    if (!grid) return;

    grid.innerHTML = '';
    const query = localState.searchQuery.trim().toLowerCase();
    const filterRole = localState.activeRoleFilter;
    const cs = state.champSelect;
    const isBanMode = cs.actionPhase === 'BAN';

    const filtered = localState.champions.filter(champ => {
      const matchesSearch = !query || champ.name.toLowerCase().includes(query) || champ.key.toLowerCase().includes(query);
      const matchesRole = filterRole === 'ALL' || champ.roles.includes(filterRole);
      return matchesSearch && matchesRole;
    });

    filtered.forEach(champ => {
      const card = document.createElement('div');
      const isSelected = localState.selectedChampionId === champ.id;
      const isBanned = cs.bans.myTeamBans.includes(champ.id) || cs.bans.theirTeamBans.includes(champ.id);

      card.className = `champ-card ${isSelected ? 'selected' : ''} ${isBanMode && isSelected ? 'ban-mode' : ''} ${isBanned ? 'banned' : ''}`;
      card.setAttribute('data-champ-id', champ.id);

      card.innerHTML = `
        <div class="champ-img-box">
          <img class="champ-img" src="${getChampionIconUrl(champ.key)}" alt="${escapeHtml(champ.name)}" loading="lazy">
        </div>
        <span class="champ-card-name">${escapeHtml(champ.name)}</span>
      `;

      card.addEventListener('click', () => {
        onChampionCardClick(champ);
      });

      grid.appendChild(card);
    });
  }

  function onChampionCardClick(champ) {
    playClickSound();
    localState.selectedChampionId = champ.id;

    const cs = state.champSelect;
    cs.myPickIntent = champ.id;

    // Optimistically update local player pick intent in roster
    if (Array.isArray(cs.myTeam)) {
      cs.myTeam.forEach(m => {
        if (m.isLocalPlayer || m.cellId === cs.cellId) {
          m.championPickIntent = champ.id;
          if (!m.isLocked) {
            m.displayedChampionId = champ.id;
            m.isPickIntent = true;
          }
        }
      });
    }

    // Highlight selected card
    document.querySelectorAll('.champ-card').forEach(c => {
      if (Number(c.getAttribute('data-champ-id')) === champ.id) {
        c.classList.add('selected');
        if (cs.actionPhase === 'BAN' && cs.isMyTurn) {
          c.classList.add('ban-mode');
        } else if (!cs.isMyTurn) {
          c.classList.add('preselected');
        }
      } else {
        c.classList.remove('selected', 'ban-mode', 'preselected');
      }
    });

    // Update Action Bar & Rosters
    renderChampSelectActionBar();
    renderTeamRosters();

    // Determine action ID (active action if my turn, otherwise local pick action)
    const targetActionId = (cs.isMyTurn && cs.activeAction)
      ? cs.activeAction.id
      : (cs.localPickActionId || 0);

    // Send hover / preselection to LCU / Backend immediately
    sendApiRequest('/api/champ-select/hover', {
      actionId: targetActionId,
      championId: champ.id
    });
  }

  // Summoner Spells Modal
  function renderSpellsModal() {
    const grid = document.getElementById('spells-grid');
    if (!grid) return;

    grid.innerHTML = '';
    localState.spells.forEach(spell => {
      const card = document.createElement('div');
      card.className = 'spell-select-card';
      card.innerHTML = `
        <img class="spell-card-img" src="${getSpellIconUrl(spell)}" alt="${escapeHtml(spell.name)}">
        <div class="spell-card-info">
          <span class="spell-card-name">${escapeHtml(spell.name)}</span>
          <span class="spell-card-cd">${spell.cooldown}s CD</span>
        </div>
      `;

      card.addEventListener('click', () => {
        onSpellSelected(spell);
      });

      grid.appendChild(card);
    });
  }

  function openSpellsModal(slotNumber) {
    playClickSound();
    localState.selectedSpellSlot = slotNumber;
    const title = document.getElementById('sheet-spells-title');
    if (title) {
      title.textContent = `Select Summoner Spell ${slotNumber === 1 ? '(Slot D)' : '(Slot F)'}`;
    }
    const modal = document.getElementById('modal-spells');
    if (modal) modal.classList.remove('hidden');
  }

  function closeSpellsModal() {
    playClickSound();
    const modal = document.getElementById('modal-spells');
    if (modal) modal.classList.add('hidden');
  }

  async function onSpellSelected(spell) {
    playClickSound();
    const slot = localState.selectedSpellSlot;
    const currentS1 = state.champSelect.mySelection.spell1Id;
    const currentS2 = state.champSelect.mySelection.spell2Id;

    let newS1 = slot === 1 ? spell.id : currentS1;
    let newS2 = slot === 2 ? spell.id : currentS2;

    // Prevent duplicate spell: swap if necessary
    if (slot === 1 && newS1 === newS2) newS2 = currentS1;
    if (slot === 2 && newS2 === newS1) newS1 = currentS2;

    state.champSelect.mySelection.spell1Id = newS1;
    state.champSelect.mySelection.spell2Id = newS2;

    closeSpellsModal();
    renderChampSelectView();

    await sendApiRequest('/api/champ-select/spells', {
      spell1Id: newS1,
      spell2Id: newS2
    });
  }

  // 6. In-Game View
  function renderInGameView() {
    const champId = state.champSelect.mySelection.selectedChampionId;
    const champ = localState.championsMap.get(champId);
    const champIcon = document.getElementById('in-game-champ-icon');
    const champName = document.getElementById('in-game-champ-name');

    if (champ && champIcon && champName) {
      champIcon.src = getChampionIconUrl(champ.key);
      champName.textContent = champ.name;
    }
  }

  // =========================================================================
  // User Actions & Event Handlers
  // =========================================================================

  function setupEventListeners() {
    // Unlock Audio Context on first interaction
    const unlockAudio = () => {
      initAudioContext();
      window.removeEventListener('click', unlockAudio);
      window.removeEventListener('touchstart', unlockAudio);
    };
    window.addEventListener('click', unlockAudio, { passive: true });
    window.addEventListener('touchstart', unlockAudio, { passive: true });

    // Sound toggle
    const btnSound = document.getElementById('btn-sound');
    if (btnSound) {
      btnSound.addEventListener('click', () => {
        localState.soundEnabled = !localState.soundEnabled;
        localStorage.setItem('lol_sound_enabled', localState.soundEnabled);
        btnSound.classList.toggle('active', localState.soundEnabled);
        document.getElementById('sound-icon').textContent = localState.soundEnabled ? '🔊' : '🔇';
        if (localState.soundEnabled) {
          initAudioContext();
          playClickSound();
        }
      });
      // Initial UI
      btnSound.classList.toggle('active', localState.soundEnabled);
      const sIcon = document.getElementById('sound-icon');
      if (sIcon) sIcon.textContent = localState.soundEnabled ? '🔊' : '🔇';
    }

    // Wake Lock toggle
    const btnWakeLock = document.getElementById('btn-wakelock');
    if (btnWakeLock) {
      btnWakeLock.addEventListener('click', () => {
        if (localState.wakeLock) {
          releaseWakeLock();
        } else {
          requestWakeLock();
        }
      });
    }

    // Standby Reconnect button
    const btnReconnect = document.getElementById('btn-reconnect');
    if (btnReconnect) {
      btnReconnect.addEventListener('click', () => {
        playClickSound();
        connectWebSocket();
        fetchStateREST();
      });
    }

    // Connect Phone / QR Code Modal
    const btnConnectPhone = document.getElementById('btn-connect-phone');
    const btnStandbyQr = document.getElementById('btn-standby-qr');
    const qrBackdrop = document.getElementById('qr-modal-backdrop');
    const qrClose = document.getElementById('qr-modal-close');
    const btnCopyQr = document.getElementById('btn-copy-qr-url');
    const qrSelect = document.getElementById('qr-adapter-select');

    if (btnConnectPhone) btnConnectPhone.addEventListener('click', openQrModal);
    if (btnStandbyQr) btnStandbyQr.addEventListener('click', openQrModal);
    if (qrBackdrop) qrBackdrop.addEventListener('click', closeQrModal);
    if (qrClose) qrClose.addEventListener('click', closeQrModal);

    if (btnCopyQr) {
      btnCopyQr.addEventListener('click', () => {
        const urlInput = document.getElementById('qr-url-input');
        if (urlInput && urlInput.value) {
          navigator.clipboard.writeText(urlInput.value).then(() => {
            const copyBtnText = document.getElementById('copy-btn-text');
            if (copyBtnText) copyBtnText.textContent = 'COPIED! ✓';
            showToast('LAN URL copied to clipboard!', 'success');
            playClickSound();
            setTimeout(() => {
              if (copyBtnText) copyBtnText.textContent = 'COPY';
            }, 2000);
          }).catch(() => {
            urlInput.select();
            document.execCommand('copy');
            showToast('LAN URL copied!', 'success');
          });
        }
      });
    }

    if (qrSelect) {
      qrSelect.addEventListener('change', () => {
        const selectedUrl = qrSelect.value;
        const urlInput = document.getElementById('qr-url-input');
        if (urlInput) urlInput.value = selectedUrl;
      });
    }

    function onQueueButtonClicked(btn) {
      playClickSound();
      triggerVibrate([40]);
      const queueId = Number(btn.getAttribute('data-queue-id'));
      const queueName = btn.querySelector('.q-name')?.textContent || 'Queue';

      // Optimistically update active state immediately for instant tactile response
      document.querySelectorAll('.queue-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      state.lobby.queueId = queueId;
      state.lobby.queueName = queueName;
      const queueBadge = document.getElementById('current-queue-badge');
      if (queueBadge) {
        queueBadge.textContent = queueName;
      }

      sendApiRequest('/api/lobby/create', { queueId });
    }

    // Queue Selectors in Lobby
    document.querySelectorAll('.queue-btn').forEach(btn => {
      btn.addEventListener('click', () => onQueueButtonClicked(btn));
    });
    // Role Selectors
    const selectP = document.getElementById('select-role-primary');
    const selectS = document.getElementById('select-role-secondary');
    const pIcon = document.getElementById('primary-role-icon');
    const sIcon = document.getElementById('secondary-role-icon');

    if (selectP && selectS) {
      const onRoleChange = () => {
        if (pIcon) pIcon.textContent = selectP.value.substring(0, 3);
        if (sIcon) sIcon.textContent = selectS.value.substring(0, 3);
        sendApiRequest('/api/lobby/positions', {
          first: selectP.value,
          second: selectS.value
        });
      };
      selectP.addEventListener('change', onRoleChange);
      selectS.addEventListener('change', onRoleChange);
    }

    // Start Queue
    const btnStart = document.getElementById('btn-start-queue');
    if (btnStart) {
      btnStart.addEventListener('click', () => {
        playClickSound();
        sendApiRequest('/api/lobby/queue/start');
      });
    }

    // Create Lobby
    const btnCreate = document.getElementById('btn-create-lobby');
    if (btnCreate) {
      btnCreate.addEventListener('click', () => {
        playClickSound();
        sendApiRequest('/api/lobby/create', { queueId: state.lobby.queueId || 420 });
      });
    }

    // Cancel Queue
    const btnCancel = document.getElementById('btn-cancel-queue');
    if (btnCancel) {
      btnCancel.addEventListener('click', () => {
        playClickSound();
        sendApiRequest('/api/lobby/queue/cancel');
      });
    }

    // Ready Check Accept
    const btnAccept = document.getElementById('btn-ready-accept');
    if (btnAccept) {
      btnAccept.addEventListener('click', () => {
        playClickSound();
        triggerVibrate([80]);
        state.readyCheck.playerResponse = 'Accepted';
        renderReadyCheckView();
        sendApiRequest('/api/matchmaking/accept');
      });
    }

    // Ready Check Decline
    const btnDecline = document.getElementById('btn-ready-decline');
    if (btnDecline) {
      btnDecline.addEventListener('click', () => {
        playClickSound();
        state.readyCheck.playerResponse = 'Declined';
        renderReadyCheckView();
        sendApiRequest('/api/matchmaking/decline');
      });
    }

    // Champ Select Search Input
    const searchInput = document.getElementById('champ-search-input');
    const searchClear = document.getElementById('champ-search-clear');
    if (searchInput && searchClear) {
      searchInput.addEventListener('input', () => {
        localState.searchQuery = searchInput.value;
        searchClear.classList.toggle('hidden', !searchInput.value);
        renderChampionsGrid();
      });
      searchClear.addEventListener('click', () => {
        searchInput.value = '';
        localState.searchQuery = '';
        searchClear.classList.add('hidden');
        renderChampionsGrid();
      });
    }

    // Champ Select Role Tabs
    document.querySelectorAll('.role-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        playClickSound();
        document.querySelectorAll('.role-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        localState.activeRoleFilter = tab.getAttribute('data-role') || 'ALL';
        renderChampionsGrid();
      });
    });

    // Spells Trigger Buttons
    const btnSpell1 = document.getElementById('btn-spell-1');
    const btnSpell2 = document.getElementById('btn-spell-2');
    if (btnSpell1) btnSpell1.addEventListener('click', () => openSpellsModal(1));
    if (btnSpell2) btnSpell2.addEventListener('click', () => openSpellsModal(2));

    const sheetBackdrop = document.getElementById('sheet-spells-backdrop');
    const sheetClose = document.getElementById('sheet-spells-close');
    if (sheetBackdrop) sheetBackdrop.addEventListener('click', closeSpellsModal);
    if (sheetClose) sheetClose.addEventListener('click', closeSpellsModal);

    // Champ Select Lock-in / Ban / Pre-select Action Button
    const btnAction = document.getElementById('btn-cs-action');
    if (btnAction) {
      btnAction.addEventListener('click', async () => {
        const cs = state.champSelect;
        const champId = localState.selectedChampionId || cs.myPickIntent || cs.mySelection.selectedChampionId;
        if (!champId) return;

        playLockInSound();
        triggerVibrate([100]);

        if (cs.isMyTurn && cs.activeAction) {
          // Active Turn (Lock in Pick or Ban)
          await sendApiRequest('/api/champ-select/action', {
            actionId: cs.activeAction.id,
            championId: champId,
            completed: true
          });
        } else {
          // Pre-select Pick Intent confirmation
          const targetActionId = cs.localPickActionId || 0;
          await sendApiRequest('/api/champ-select/hover', {
            actionId: targetActionId,
            championId: champId
          });

          // Visual feedback
          const actionBtnText = document.getElementById('cs-action-btn-text');
          if (actionBtnText) {
            actionBtnText.textContent = 'PRE-SELECTED ✓';
            setTimeout(() => {
              renderChampSelectActionBar();
            }, 1200);
          }
        }
      });
    }
  }

  // =========================================================================
  // Phone Connect & QR Modal Controller
  // =========================================================================

  let cachedNetworkInfo = null;

  async function openQrModal() {
    const modal = document.getElementById('modal-connect-phone');
    if (!modal) return;

    modal.classList.remove('hidden');
    playClickSound();

    try {
      const res = await fetch('/api/network-info');
      if (res.ok) {
        cachedNetworkInfo = await res.json();
        renderQrModalContent(cachedNetworkInfo);
      } else {
        renderQrModalFallback();
      }
    } catch (e) {
      renderQrModalFallback();
    }
  }

  function closeQrModal() {
    const modal = document.getElementById('modal-connect-phone');
    if (modal) {
      modal.classList.add('hidden');
      playClickSound();
    }
  }

  function renderQrModalContent(data) {
    const qrContainer = document.getElementById('qr-svg-container');
    const urlInput = document.getElementById('qr-url-input');
    const adaptersContainer = document.getElementById('qr-adapters-container');
    const adapterSelect = document.getElementById('qr-adapter-select');

    const primaryUrl = data.primary_url || `http://${window.location.hostname}:8000`;

    if (urlInput) {
      urlInput.value = primaryUrl;
    }

    if (qrContainer) {
      if (data.qr_svg) {
        qrContainer.innerHTML = data.qr_svg;
      } else {
        qrContainer.innerHTML = `<div class="qr-loading">Open URL on phone: <br><strong>${escapeHtml(primaryUrl)}</strong></div>`;
      }
    }

    if (adaptersContainer && adapterSelect && Array.isArray(data.interfaces) && data.interfaces.length > 1) {
      adapterSelect.innerHTML = '';
      data.interfaces.forEach(iface => {
        const opt = document.createElement('option');
        opt.value = iface.url;
        opt.textContent = `${iface.ip} (${iface.interface} - ${iface.type})`;
        if (iface.is_primary) opt.selected = true;
        adapterSelect.appendChild(opt);
      });
      adaptersContainer.classList.remove('hidden');
    } else if (adaptersContainer) {
      adaptersContainer.classList.add('hidden');
    }
  }

  function renderQrModalFallback() {
    const qrContainer = document.getElementById('qr-svg-container');
    const urlInput = document.getElementById('qr-url-input');
    const lanUrl = `http://${window.location.hostname}:8000`;

    if (urlInput) urlInput.value = lanUrl;
    if (qrContainer) {
      qrContainer.innerHTML = `<div class="qr-loading">Open on phone (same Wi-Fi):<br><strong>${escapeHtml(lanUrl)}</strong></div>`;
    }
  }
  // =========================================================================
  // Utility Helpers
  // =========================================================================

  function formatTimeSeconds(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // =========================================================================
  // App Initialization
  // =========================================================================

  async function init() {
    setupEventListeners();
    await loadCatalogs();
    connectWebSocket();
    fetchStateREST();
    startTimerEngine();
  }

  // Run on DOM loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

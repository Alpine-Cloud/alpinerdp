<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS, DELETE');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    exit(0);
}

// Config - make sure these files are writable
$AVAILABLE_FILE = 'available_rdp.txt';
$IN_USE_FILE = 'in_use_rdp.txt';
$LOG_FILE = 'rdp_pool_log.txt';

// Initialize files if they don't exist
if (!file_exists($AVAILABLE_FILE)) {
    file_put_contents($AVAILABLE_FILE, '');
}
if (!file_exists($IN_USE_FILE)) {
    file_put_contents($IN_USE_FILE, '');
}
if (!file_exists($LOG_FILE)) {
    file_put_contents($LOG_FILE, '');
}

function logEvent($message) {
    global $LOG_FILE;
    $timestamp = date('Y-m-d H:i:s');
    file_put_contents($LOG_FILE, "[$timestamp] $message\n", FILE_APPEND | LOCK_EX);
}

function getAvailableRDPs() {
    global $AVAILABLE_FILE;
    if (!file_exists($AVAILABLE_FILE)) return [];
    
    $content = file_get_contents($AVAILABLE_FILE);
    if (empty(trim($content))) return [];
    
    $lines = file($AVAILABLE_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $available = [];
    
    foreach ($lines as $line) {
        $parts = explode(' | ', $line);
        if (count($parts) >= 3) {
            $available[] = [
                'ip' => $parts[0],
                'username' => $parts[1],
                'password' => $parts[2],
                'added_at' => $parts[3] ?? date('Y-m-d H:i:s')
            ];
        }
    }
    return $available;
}

function getInUseRDPs() {
    global $IN_USE_FILE;
    if (!file_exists($IN_USE_FILE)) return [];
    
    $content = file_get_contents($IN_USE_FILE);
    if (empty(trim($content))) return [];
    
    $lines = file($IN_USE_FILE, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    $in_use = [];
    
    foreach ($lines as $line) {
        $parts = explode(' | ', $line);
        if (count($parts) >= 4) {
            $in_use[] = [
                'ip' => $parts[0],
                'username' => $parts[1],
                'password' => $parts[2],
                'user_id' => $parts[3],
                'claimed_at' => $parts[4] ?? date('Y-m-d H:i:s')
            ];
        }
    }
    return $in_use;
}

function saveAvailableRDPs($rdpList) {
    global $AVAILABLE_FILE;
    $lines = [];
    foreach ($rdpList as $rdp) {
        $lines[] = implode(' | ', [
            $rdp['ip'],
            $rdp['username'],
            $rdp['password'],
            $rdp['added_at'] ?? date('Y-m-d H:i:s')
        ]);
    }
    $result = file_put_contents($AVAILABLE_FILE, implode("\n", $lines) . "\n", LOCK_EX);
    return $result !== false;
}

function saveInUseRDPs($rdpList) {
    global $IN_USE_FILE;
    $lines = [];
    foreach ($rdpList as $rdp) {
        $lines[] = implode(' | ', [
            $rdp['ip'],
            $rdp['username'],
            $rdp['password'],
            $rdp['user_id'],
            $rdp['claimed_at'] ?? date('Y-m-d H:i:s')
        ]);
    }
    $result = file_put_contents($IN_USE_FILE, implode("\n", $lines) . "\n", LOCK_EX);
    return $result !== false;
}

function generateUserID() {
    return uniqid('user_', true);
}

function cleanupExpiredRDPs() {
    $in_use = getInUseRDPs();
    $available = getAvailableRDPs();
    $now = time();
    $expired_found = false;
    
    foreach ($in_use as $key => $rdp) {
        $claimed_time = strtotime($rdp['claimed_at']);
        // 6 hours expiration
        if (($now - $claimed_time) > (6 * 3600)) {
            // Move expired RDP back to available
            $available[] = [
                'ip' => $rdp['ip'],
                'username' => $rdp['username'],
                'password' => $rdp['password'],
                'added_at' => date('Y-m-d H:i:s')
            ];
            unset($in_use[$key]);
            $expired_found = true;
            logEvent("RDP EXPIRED: {$rdp['ip']} - auto returned to pool");
        }
    }
    
    if ($expired_found) {
        saveInUseRDPs(array_values($in_use));
        saveAvailableRDPs($available);
        return true;
    }
    return false;
}

function sendJSONResponse($data, $statusCode = 200) {
    http_response_code($statusCode);
    echo json_encode($data, JSON_PRETTY_PRINT);
    exit;
}

// Handle POST - Add new RDP to available pool
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $input = json_decode(file_get_contents('php://input'), true);
    
    // Also try form data if JSON fails
    if (!$input || json_last_error() !== JSON_ERROR_NONE) {
        $input = $_POST;
    }
    
    $ip = trim($input['ip'] ?? '');
    $username = trim($input['username'] ?? '');
    $password = trim($input['password'] ?? '');
    
    if (empty($ip) || empty($username) || empty($password)) {
        sendJSONResponse([
            'success' => false,
            'error' => 'Missing IP, username, or password',
            'received' => ['ip' => $ip, 'username' => $username, 'password' => !empty($password) ? '***' : '']
        ], 400);
    }
    
    // Cleanup expired RDPs first
    cleanupExpiredRDPs();
    
    // Add to available pool
    $available = getAvailableRDPs();
    
    // Check if this IP already exists in pool
    foreach ($available as $existing) {
        if ($existing['ip'] === $ip) {
            sendJSONResponse([
                'success' => false,
                'error' => 'RDP with this IP already exists in pool',
                'existing_ip' => $ip
            ], 409);
        }
    }
    
    $newRDP = [
        'ip' => $ip,
        'username' => $username,
        'password' => $password,
        'added_at' => date('Y-m-d H:i:s')
    ];
    
    $available[] = $newRDP;
    
    if (saveAvailableRDPs($available)) {
        logEvent("RDP ADDED: $ip - $username");
        sendJSONResponse([
            'success' => true, 
            'message' => 'RDP added to pool',
            'rdp' => $newRDP,
            'total_available' => count($available)
        ]);
    } else {
        sendJSONResponse([
            'success' => false,
            'error' => 'Failed to save RDP to pool'
        ], 500);
    }
}

// Handle GET - Claim an RDP
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'claim') {
    // Cleanup expired RDPs first
    cleanupExpiredRDPs();
    
    $available = getAvailableRDPs();
    
    if (empty($available)) {
        sendJSONResponse([
            'success' => false,
            'error' => 'No RDPs available', 
            'available_count' => 0,
            'message' => 'All RDP instances are currently in use. Please try again later.'
        ], 404);
    }
    
    // Get first available RDP
    $rdp = array_shift($available);
    $user_id = generateUserID();
    
    // Move to in-use
    $in_use = getInUseRDPs();
    $rdp['user_id'] = $user_id;
    $rdp['claimed_at'] = date('Y-m-d H:i:s');
    $in_use[] = $rdp;
    
    if (saveAvailableRDPs($available) && saveInUseRDPs($in_use)) {
        logEvent("RDP CLAIMED: {$rdp['ip']} by $user_id");
        
        sendJSONResponse([
            'success' => true,
            'rdp' => [
                'ip' => $rdp['ip'],
                'username' => $rdp['username'],
                'password' => $rdp['password'],
                'user_id' => $user_id,
                'claimed_at' => $rdp['claimed_at'],
                'expires_at' => date('Y-m-d H:i:s', strtotime('+6 hours'))
            ],
            'remaining' => count($available),
            'message' => 'RDP instance claimed successfully!'
        ]);
    } else {
        sendJSONResponse([
            'success' => false,
            'error' => 'Failed to claim RDP'
        ], 500);
    }
}

// Handle GET - Release an RDP
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'release') {
    $user_id = $_GET['user_id'] ?? '';
    
    if (empty($user_id)) {
        sendJSONResponse([
            'success' => false,
            'error' => 'Missing user_id parameter'
        ], 400);
    }
    
    $in_use = getInUseRDPs();
    $available = getAvailableRDPs();
    $released_rdp = null;
    
    // Find and remove the RDP from in-use
    foreach ($in_use as $key => $rdp) {
        if ($rdp['user_id'] === $user_id) {
            $released_rdp = $rdp;
            unset($in_use[$key]);
            
            // Add back to available pool
            $available[] = [
                'ip' => $rdp['ip'],
                'username' => $rdp['username'],
                'password' => $rdp['password'],
                'added_at' => date('Y-m-d H:i:s')
            ];
            break;
        }
    }
    
    if ($released_rdp) {
        if (saveInUseRDPs(array_values($in_use)) && saveAvailableRDPs($available)) {
            logEvent("RDP RELEASED: {$released_rdp['ip']} by $user_id");
            
            sendJSONResponse([
                'success' => true,
                'message' => 'RDP released back to pool',
                'released_rdp' => [
                    'ip' => $released_rdp['ip'],
                    'username' => $released_rdp['username']
                ],
                'available_count' => count($available)
            ]);
        } else {
            sendJSONResponse([
                'success' => false,
                'error' => 'Failed to save pool data'
            ], 500);
        }
    } else {
        sendJSONResponse([
            'success' => false,
            'error' => 'RDP not found or already released'
        ], 404);
    }
}

// Handle GET - Get pool status
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'status') {
    cleanupExpiredRDPs();
    
    $available = getAvailableRDPs();
    $in_use = getInUseRDPs();
    
    sendJSONResponse([
        'success' => true,
        'pool_status' => [
            'available_count' => count($available),
            'in_use_count' => count($in_use),
            'total_count' => count($available) + count($in_use),
            'available_ips' => array_column($available, 'ip'),
            'in_use_ips' => array_column($in_use, 'ip'),
            'timestamp' => date('Y-m-d H:i:s')
        ]
    ]);
}

// Handle GET - Test endpoint
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'test') {
    sendJSONResponse([
        'success' => true,
        'message' => 'RDP Pool API is working!',
        'timestamp' => date('Y-m-d H:i:s'),
        'endpoints' => [
            'POST /' => 'Add RDP to pool',
            'GET ?action=claim' => 'Claim an RDP',
            'GET ?action=release&user_id=XXX' => 'Release an RDP',
            'GET ?action=status' => 'Get pool status',
            'GET ?action=test' => 'Test endpoint'
        ]
    ]);
}

// Default response for unknown requests
sendJSONResponse([
    'success' => false,
    'error' => 'Invalid endpoint',
    'available_actions' => [
        'POST /' => 'Add RDP to pool',
        'GET ?action=claim' => 'Claim an RDP', 
        'GET ?action=release' => 'Release an RDP',
        'GET ?action=status' => 'Get pool status',
        'GET ?action=test' => 'Test endpoint'
    ]
], 400);
?>

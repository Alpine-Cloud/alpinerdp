<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS, DELETE');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    exit(0);
}

// Config
$AVAILABLE_FILE = 'available_rdp.txt';
$IN_USE_FILE = 'in_use_rdp.txt';
$LOG_FILE = 'rdp_pool_log.txt';

function logEvent($message) {
    global $LOG_FILE;
    $timestamp = date('Y-m-d H:i:s');
    file_put_contents($LOG_FILE, "[$timestamp] $message\n", FILE_APPEND | LOCK_EX);
}

function getAvailableRDPs() {
    global $AVAILABLE_FILE;
    if (!file_exists($AVAILABLE_FILE)) return [];
    
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
    file_put_contents($AVAILABLE_FILE, implode("\n", $lines) . "\n", LOCK_EX);
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
    file_put_contents($IN_USE_FILE, implode("\n", $lines) . "\n", LOCK_EX);
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
    }
}

// Handle POST - Add new RDP to available pool (from GitHub workflow)
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $input = json_decode(file_get_contents('php://input'), true);
    
    if (!$input) {
        $input = $_POST;
    }
    
    $ip = trim($input['ip'] ?? '');
    $username = trim($input['username'] ?? '');
    $password = trim($input['password'] ?? '');
    
    if (empty($ip) || empty($username) || empty($password)) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing IP, username, or password']);
        exit;
    }
    
    // Cleanup expired RDPs first
    cleanupExpiredRDPs();
    
    // Add to available pool
    $available = getAvailableRDPs();
    
    // Check if this IP already exists in pool
    foreach ($available as $existing) {
        if ($existing['ip'] === $ip) {
            http_response_code(409);
            echo json_encode(['error' => 'RDP with this IP already exists in pool']);
            exit;
        }
    }
    
    $available[] = [
        'ip' => $ip,
        'username' => $username,
        'password' => $password,
        'added_at' => date('Y-m-d H:i:s')
    ];
    
    saveAvailableRDPs($available);
    
    logEvent("RDP ADDED: $ip - $username");
    echo json_encode([
        'success' => true, 
        'message' => 'RDP added to pool',
        'total_available' => count($available)
    ]);
    exit;
}

// Handle GET - Claim an RDP
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'claim') {
    // Cleanup expired RDPs first
    cleanupExpiredRDPs();
    
    $available = getAvailableRDPs();
    
    if (empty($available)) {
        http_response_code(404);
        echo json_encode([
            'error' => 'No RDPs available', 
            'available_count' => 0,
            'message' => 'All RDP instances are currently in use. Please try again later.'
        ]);
        exit;
    }
    
    // Get first available RDP
    $rdp = array_shift($available);
    $user_id = generateUserID();
    
    // Move to in-use
    $in_use = getInUseRDPs();
    $rdp['user_id'] = $user_id;
    $rdp['claimed_at'] = date('Y-m-d H:i:s');
    $in_use[] = $rdp;
    
    saveAvailableRDPs($available);
    saveInUseRDPs($in_use);
    
    logEvent("RDP CLAIMED: {$rdp['ip']} by $user_id");
    
    echo json_encode([
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
    exit;
}

// Handle DELETE - Release an RDP
if ($_SERVER['REQUEST_METHOD'] === 'DELETE' || ($_GET['action'] ?? '') === 'release') {
    $input = json_decode(file_get_contents('php://input'), true) ?? $_GET;
    $user_id = $input['user_id'] ?? '';
    
    if (empty($user_id)) {
        http_response_code(400);
        echo json_encode(['error' => 'Missing user_id']);
        exit;
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
        saveInUseRDPs(array_values($in_use));
        saveAvailableRDPs($available);
        
        logEvent("RDP RELEASED: {$released_rdp['ip']} by $user_id");
        
        echo json_encode([
            'success' => true,
            'message' => 'RDP released back to pool',
            'released_rdp' => [
                'ip' => $released_rdp['ip'],
                'username' => $released_rdp['username']
            ],
            'available_count' => count($available)
        ]);
    } else {
        http_response_code(404);
        echo json_encode(['error' => 'RDP not found or already released']);
    }
    exit;
}

// Handle GET - Get pool status
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'status') {
    cleanupExpiredRDPs();
    
    $available = getAvailableRDPs();
    $in_use = getInUseRDPs();
    
    echo json_encode([
        'success' => true,
        'pool_status' => [
            'available_count' => count($available),
            'in_use_count' => count($in_use),
            'total_count' => count($available) + count($in_use),
            'available_ips' => array_column($available, 'ip'),
            'in_use_ips' => array_column($in_use, 'ip')
        ]
    ]);
    exit;
}

// Handle GET - Get all data (admin view)
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'admin') {
    $available = getAvailableRDPs();
    $in_use = getInUseRDPs();
    
    echo json_encode([
        'success' => true,
        'available' => $available,
        'in_use' => $in_use,
        'stats' => [
            'total_available' => count($available),
            'total_in_use' => count($in_use),
            'timestamp' => date('Y-m-d H:i:s')
        ]
    ]);
    exit;
}

// Handle POST - Add multiple RDPs (for testing)
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_GET['action'] ?? '') === 'add-multiple') {
    $input = json_decode(file_get_contents('php://input'), true);
    $rdps = $input['rdps'] ?? [];
    $added = 0;
    
    $available = getAvailableRDPs();
    
    foreach ($rdps as $rdp) {
        if (!empty($rdp['ip']) && !empty($rdp['username']) && !empty($rdp['password'])) {
            $available[] = [
                'ip' => $rdp['ip'],
                'username' => $rdp['username'],
                'password' => $rdp['password'],
                'added_at' => date('Y-m-d H:i:s')
            ];
            $added++;
        }
    }
    
    saveAvailableRDPs($available);
    
    echo json_encode([
        'success' => true,
        'message' => "Added $added RDPs to pool",
        'total_available' => count($available)
    ]);
    exit;
}

// Default response - API info
echo json_encode([
    'api' => 'Alpine Cloud RDP Pool System',
    'version' => '1.0',
    'endpoints' => [
        'POST /' => 'Add RDP to pool',
        'GET ?action=claim' => 'Claim an RDP',
        'GET ?action=release&user_id=XXX' => 'Release an RDP',
        'GET ?action=status' => 'Get pool status',
        'GET ?action=admin' => 'Admin view (all data)',
        'POST ?action=add-multiple' => 'Add multiple RDPs'
    ],
    'current_time' => date('Y-m-d H:i:s')
]);
?>

-- The database schema at migration 0001_baseline (October 2026), as created by
-- create_all before Alembic. Used to test upgrading an existing install. Never edit.
CREATE TABLE audit_events (
	id INTEGER NOT NULL, 
	timestamp DATETIME NOT NULL, 
	username VARCHAR(200) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	detail TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE backup_runs (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	"trigger" VARCHAR(100) NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	status VARCHAR(20) NOT NULL, 
	changed BOOLEAN NOT NULL, 
	"commit" VARCHAR(64), 
	error_type VARCHAR(30), 
	message TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE backup_state (
	device_id INTEGER NOT NULL, 
	frequency_minutes INTEGER NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	last_status VARCHAR(20) NOT NULL, 
	last_attempt DATETIME, 
	last_success DATETIME, 
	last_change DATETIME, 
	last_error_type VARCHAR(30), 
	last_error TEXT, 
	consecutive_failures INTEGER NOT NULL, 
	config_path VARCHAR(300), 
	last_commit VARCHAR(64), 
	PRIMARY KEY (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE credentials (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	username VARCHAR(200) NOT NULL, 
	password_enc TEXT NOT NULL, 
	enable_secret_enc TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
CREATE TABLE ct_circuits (
	id INTEGER NOT NULL, 
	import_id INTEGER NOT NULL, 
	row_no INTEGER NOT NULL, 
	ip_partition VARCHAR(200) NOT NULL, 
	service VARCHAR(200) NOT NULL, 
	eng_prefix VARCHAR(255) NOT NULL, 
	device_name VARCHAR(255) NOT NULL, 
	device_type VARCHAR(255) NOT NULL, 
	manufacturer VARCHAR(255) NOT NULL, 
	mac VARCHAR(100) NOT NULL, 
	floor VARCHAR(200) NOT NULL, 
	room VARCHAR(200) NOT NULL, 
	ip VARCHAR(100) NOT NULL, 
	mask VARCHAR(100) NOT NULL, 
	gateway VARCHAR(100) NOT NULL, 
	vlan VARCHAR(50) NOT NULL, 
	conn_type VARCHAR(100) NOT NULL, 
	port VARCHAR(100) NOT NULL, 
	switch VARCHAR(255) NOT NULL, 
	drawing_number VARCHAR(255) NOT NULL, 
	drawing_ref VARCHAR(255) NOT NULL, 
	switch_norm VARCHAR(255) NOT NULL, 
	port_norm VARCHAR(100) NOT NULL, 
	mac_norm VARCHAR(20) NOT NULL, 
	warnings TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(import_id) REFERENCES ct_imports (id) ON DELETE CASCADE
);
CREATE TABLE ct_device_scan (
	device_id INTEGER NOT NULL, 
	last_attempt DATETIME, 
	last_success DATETIME, 
	last_error TEXT NOT NULL, 
	mac_count INTEGER NOT NULL, 
	arp_count INTEGER NOT NULL, 
	PRIMARY KEY (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE ct_imports (
	id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	sheet VARCHAR(255) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	uploaded_by VARCHAR(200) NOT NULL, 
	uploaded_at DATETIME NOT NULL, 
	committed_by VARCHAR(200), 
	committed_at DATETIME, 
	row_count INTEGER NOT NULL, 
	warning_count INTEGER NOT NULL, 
	summary TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE ct_live_arp (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	ip VARCHAR(100) NOT NULL, 
	mac_norm VARCHAR(20) NOT NULL, 
	seen_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE ct_live_mac (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	mac_norm VARCHAR(20) NOT NULL, 
	vlan VARCHAR(50) NOT NULL, 
	port VARCHAR(100) NOT NULL, 
	port_norm VARCHAR(100) NOT NULL, 
	uplink BOOLEAN NOT NULL, 
	seen_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE ct_mac_last_seen (
	mac_norm VARCHAR(20) NOT NULL, 
	device_id INTEGER, 
	port VARCHAR(100) NOT NULL, 
	vlan VARCHAR(50) NOT NULL, 
	seen_at DATETIME NOT NULL, 
	PRIMARY KEY (mac_norm), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE SET NULL
);
CREATE TABLE ct_scans (
	id INTEGER NOT NULL, 
	"trigger" VARCHAR(200) NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	devices_ok INTEGER NOT NULL, 
	devices_failed INTEGER NOT NULL, 
	errors TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE devices (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	address VARCHAR(255) NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	site VARCHAR(100) NOT NULL, 
	credential_id INTEGER, 
	enabled BOOLEAN NOT NULL, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	FOREIGN KEY(credential_id) REFERENCES credentials (id) ON DELETE RESTRICT
);
CREATE TABLE fw_device_facts (
	device_id INTEGER NOT NULL, 
	last_status VARCHAR(20) NOT NULL, 
	last_attempt DATETIME, 
	last_success DATETIME, 
	last_error_type VARCHAR(30), 
	last_error TEXT, 
	model VARCHAR(100), 
	serial VARCHAR(100), 
	version VARCHAR(100), 
	image VARCHAR(300), 
	boot_mode VARCHAR(20), 
	ha_role VARCHAR(100), 
	flash_total BIGINT, 
	flash_free BIGINT, 
	version_changed_at DATETIME, 
	previous_version VARCHAR(100), 
	PRIMARY KEY (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE
);
CREATE TABLE fw_device_settings (
	device_id INTEGER NOT NULL, 
	upgrade_credential_id INTEGER, 
	default_path VARCHAR(50) NOT NULL, 
	peer_device_id INTEGER, 
	fdm_fingerprint VARCHAR(100) NOT NULL, 
	file_system VARCHAR(30) NOT NULL, 
	PRIMARY KEY (device_id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE CASCADE, 
	FOREIGN KEY(upgrade_credential_id) REFERENCES credentials (id) ON DELETE RESTRICT, 
	FOREIGN KEY(peer_device_id) REFERENCES devices (id) ON DELETE SET NULL
);
CREATE TABLE fw_image_info (
	image_id INTEGER NOT NULL, 
	recommended BOOLEAN NOT NULL, 
	release_ref VARCHAR(500) NOT NULL, 
	PRIMARY KEY (image_id), 
	FOREIGN KEY(image_id) REFERENCES fw_images (id) ON DELETE CASCADE
);
CREATE TABLE fw_images (
	id INTEGER NOT NULL, 
	filename VARCHAR(200) NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	version VARCHAR(100) NOT NULL, 
	model_pattern VARCHAR(100) NOT NULL, 
	size BIGINT NOT NULL, 
	md5 VARCHAR(32) NOT NULL, 
	sha512 VARCHAR(128) NOT NULL, 
	verified BOOLEAN NOT NULL, 
	notes TEXT NOT NULL, 
	uploaded_by VARCHAR(200) NOT NULL, 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (filename)
);
CREATE TABLE fw_job_checks (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	device_id INTEGER, 
	phase VARCHAR(10) NOT NULL, 
	run_no INTEGER NOT NULL, 
	check_id VARCHAR(50) NOT NULL, 
	label VARCHAR(200) NOT NULL, 
	severity VARCHAR(10) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	value TEXT NOT NULL, 
	detail TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	overridden_by VARCHAR(200), 
	override_reason TEXT, 
	overridden_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE
);
CREATE TABLE fw_job_circuits (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	stage VARCHAR(10) NOT NULL, 
	source VARCHAR(300) NOT NULL, 
	count INTEGER NOT NULL, 
	data TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE
);
CREATE TABLE fw_job_events (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	device_id INTEGER, 
	time DATETIME NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	step VARCHAR(50) NOT NULL, 
	message TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE
);
CREATE TABLE fw_job_requests (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	action VARCHAR(20) NOT NULL, 
	username VARCHAR(200) NOT NULL, 
	requested_at DATETIME NOT NULL, 
	claimed_at DATETIME, 
	claimed_by VARCHAR(100) NOT NULL, 
	finished_at DATETIME, 
	result TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE
);
CREATE TABLE fw_job_snapshots (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	device_id INTEGER, 
	phase VARCHAR(10) NOT NULL, 
	run_no INTEGER NOT NULL, 
	data TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE
);
CREATE TABLE fw_job_units (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	position INTEGER NOT NULL, 
	role VARCHAR(50) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	from_version VARCHAR(100) NOT NULL, 
	running_image VARCHAR(300) NOT NULL, 
	rollback_ref VARCHAR(100) NOT NULL, 
	staged BOOLEAN NOT NULL, 
	image_present BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (job_id, device_id), 
	FOREIGN KEY(job_id) REFERENCES fw_jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE RESTRICT
);
CREATE TABLE fw_jobs (
	id INTEGER NOT NULL, 
	device_id INTEGER NOT NULL, 
	image_id INTEGER NOT NULL, 
	path VARCHAR(50) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	dry_run BOOLEAN NOT NULL, 
	from_version VARCHAR(100) NOT NULL, 
	target_version VARCHAR(100) NOT NULL, 
	change_ref VARCHAR(100) NOT NULL, 
	notes TEXT NOT NULL, 
	planned_start DATETIME, 
	planned_end DATETIME, 
	created_by VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	started_by VARCHAR(200), 
	started_at DATETIME, 
	finished_at DATETIME, 
	outcome_note TEXT NOT NULL, 
	pre_backup_commit VARCHAR(64), 
	post_backup_commit VARCHAR(64), 
	pre_run INTEGER NOT NULL, 
	post_run INTEGER NOT NULL, 
	stage_run INTEGER NOT NULL, 
	"plan" TEXT NOT NULL, 
	step_index INTEGER NOT NULL, 
	current_step VARCHAR(200) NOT NULL, 
	stop_requested BOOLEAN NOT NULL, 
	staged_at DATETIME, 
	pending_commit BOOLEAN NOT NULL, 
	abort_deadline DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id) ON DELETE RESTRICT, 
	FOREIGN KEY(image_id) REFERENCES fw_images (id) ON DELETE RESTRICT
);
CREATE TABLE fw_standards (
	id INTEGER NOT NULL, 
	platform VARCHAR(50) NOT NULL, 
	model_pattern VARCHAR(100) NOT NULL, 
	target_version VARCHAR(100) NOT NULL, 
	image_id INTEGER, 
	notes TEXT NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (platform, model_pattern), 
	FOREIGN KEY(image_id) REFERENCES fw_images (id) ON DELETE SET NULL
);
CREATE TABLE fw_worker_status (
	id INTEGER NOT NULL, 
	pid INTEGER NOT NULL, 
	host VARCHAR(200) NOT NULL, 
	started_at DATETIME NOT NULL, 
	beat_at DATETIME NOT NULL, 
	job_id INTEGER, 
	step VARCHAR(200) NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(200) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	display_name VARCHAR(200) NOT NULL, 
	email VARCHAR(200) NOT NULL, 
	password_hash TEXT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	permissions TEXT NOT NULL, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	updated_at DATETIME NOT NULL, 
	updated_by VARCHAR(200) NOT NULL, 
	last_login DATETIME, 
	password_changed_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);
CREATE INDEX ix_audit_events_timestamp ON audit_events (timestamp);
CREATE INDEX ix_backup_runs_device_id ON backup_runs (device_id);
CREATE INDEX ix_backup_runs_started_at ON backup_runs (started_at);
CREATE INDEX ix_ct_circuits_import_id ON ct_circuits (import_id);
CREATE INDEX ix_ct_circuits_switch_norm ON ct_circuits (switch_norm);
CREATE INDEX ix_ct_imports_status ON ct_imports (status);
CREATE INDEX ix_ct_live_arp_device_id ON ct_live_arp (device_id);
CREATE INDEX ix_ct_live_arp_ip ON ct_live_arp (ip);
CREATE INDEX ix_ct_live_mac_device_id ON ct_live_mac (device_id);
CREATE INDEX ix_ct_live_mac_mac_norm ON ct_live_mac (mac_norm);
CREATE INDEX ix_fw_job_checks_job_id ON fw_job_checks (job_id);
CREATE INDEX ix_fw_job_circuits_job_id ON fw_job_circuits (job_id);
CREATE INDEX ix_fw_job_events_job_id ON fw_job_events (job_id);
CREATE INDEX ix_fw_job_requests_claimed_at ON fw_job_requests (claimed_at);
CREATE INDEX ix_fw_job_requests_job_id ON fw_job_requests (job_id);
CREATE INDEX ix_fw_job_snapshots_job_id ON fw_job_snapshots (job_id);
CREATE INDEX ix_fw_job_units_device_id ON fw_job_units (device_id);
CREATE INDEX ix_fw_job_units_job_id ON fw_job_units (job_id);
CREATE INDEX ix_fw_jobs_device_id ON fw_jobs (device_id);
CREATE INDEX ix_fw_jobs_status ON fw_jobs (status);

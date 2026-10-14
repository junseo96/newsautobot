CREATE TABLE `grid_assets` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`kind` text NOT NULL,
	`region` text NOT NULL,
	`state` text,
	`queue_id` text,
	`official_project_id` text,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `grid_assets_region` ON `grid_assets` (`region`);--> statement-breakpoint
CREATE TABLE `grid_events` (
	`id` text PRIMARY KEY NOT NULL,
	`asset_id` text NOT NULL,
	`region` text NOT NULL,
	`gate` text NOT NULL,
	`status` text NOT NULL,
	`published_at` text,
	`observed_at` text NOT NULL,
	`payload` text NOT NULL,
	`telegram_status` text NOT NULL,
	`dashboard_status` text NOT NULL,
	`matched_project_id` text,
	`ingested_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `grid_events_asset_date` ON `grid_events` (`asset_id`,`published_at`);--> statement-breakpoint
CREATE INDEX `grid_events_region_date` ON `grid_events` (`region`,`published_at`);--> statement-breakpoint
CREATE INDEX `grid_events_project` ON `grid_events` (`matched_project_id`);--> statement-breakpoint
CREATE TABLE `grid_sync_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`at` text NOT NULL,
	`status` text NOT NULL,
	`details` text NOT NULL
);

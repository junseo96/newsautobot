CREATE TABLE `datasets` (
	`key` text PRIMARY KEY NOT NULL,
	`kind` text NOT NULL,
	`region` text NOT NULL,
	`source_as_of` text NOT NULL,
	`source_url` text NOT NULL,
	`payload` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `settings` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `snapshots` (
	`id` text PRIMARY KEY NOT NULL,
	`region` text NOT NULL,
	`observed_at` text NOT NULL,
	`payload` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `snapshots_region_date` ON `snapshots` (`region`,`observed_at`);--> statement-breakpoint
CREATE TABLE `update_runs` (
	`id` text PRIMARY KEY NOT NULL,
	`checked_at` text NOT NULL,
	`status` text NOT NULL,
	`details` text NOT NULL
);

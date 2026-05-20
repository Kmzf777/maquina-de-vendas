-- Extend message_templates.status to include 'approved' and 'rejected'
-- so that Meta template approval/rejection webhooks can update the local status.
ALTER TABLE message_templates DROP CONSTRAINT IF EXISTS message_templates_status_check;
ALTER TABLE message_templates ADD CONSTRAINT message_templates_status_check
  CHECK (status IN ('pending', 'pending_category_review', 'approved', 'rejected', 'cancelled'));

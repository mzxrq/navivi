import { Trans } from "@lingui/react/macro";
import { Dialog, dialogButton } from "./Dialog";

interface UnsavedChangesProps {
  isOpen: boolean;
  projectName: string;
  onCancel: () => void;
  onDiscard: () => void;
  onSave: () => void;
}

export function UnsavedChanges({
  isOpen,
  projectName,
  onCancel,
  onDiscard,
  onSave,
}: UnsavedChangesProps) {
  if (!isOpen) return null;

  return (
    <Dialog
      title={<Trans>Unsaved Changes</Trans>}
      onClose={onCancel}
      footer={
        <>
          {/* Destructive choice sits apart from Cancel / Save. */}
          <button
            type="button"
            onClick={onDiscard}
            className={`${dialogButton.secondary} mr-auto text-red-600! dark:text-red-400! hover:bg-red-500/10!`}
          >
            <Trans>Don't Save</Trans>
          </button>
          <button type="button" onClick={onCancel} className={dialogButton.secondary}>
            <Trans>Cancel</Trans>
          </button>
          <button type="button" onClick={onSave} className={dialogButton.primary} autoFocus>
            <Trans>Save</Trans>
          </button>
        </>
      }
    >
      <p className="text-[13px] leading-relaxed text-zinc-600 dark:text-zinc-300">
        <Trans>Do you want to save the changes you made to </Trans>
        <span className="font-medium text-zinc-900 dark:text-zinc-100">{projectName}</span>?
      </p>
    </Dialog>
  );
}

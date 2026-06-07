import type { ReactNode } from "react";
import { affiliateUrl, isAffiliate } from "../affiliate/affiliateUrl";
import { DisclosureBadge } from "./DisclosureBadge";

interface Props {
  brand: string;
  url: string;
  children: ReactNode;
  className?: string;
  showBadge?: boolean;
}

// Outbound product link. When the brand has a configured affiliate code the link is
// monetized (rel="sponsored") and a DisclosureBadge is shown next to it; otherwise it
// is a plain product link.
export function AffiliateLink({ brand, url, children, className, showBadge = true }: Props) {
  const affiliate = isAffiliate(brand);
  const href = affiliateUrl(brand, url);
  return (
    <span className="inline-flex items-center gap-1.5">
      <a
        href={href}
        target="_blank"
        rel={affiliate ? "sponsored nofollow noopener" : "noopener noreferrer"}
        referrerPolicy="no-referrer-when-downgrade"
        className={className}
      >
        {children}
      </a>
      {affiliate && showBadge && <DisclosureBadge />}
    </span>
  );
}
